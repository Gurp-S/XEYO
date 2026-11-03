import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { loadDshPackage } from './lib/resolve.js'
import { adjust, decide, usedPercent } from './lib/timing.js'
import { selectCompactableRange } from './lib/range.js'
import { admitCompaction } from './lib/admission.js'
import { buildCheckpoint, buildSelectiveCheckpoint, mandatoryLowerBound } from './lib/checkpoint.js'
import { byteLength } from './lib/bytes.js'
import { createDenoiseState, runtimeDenoise } from './lib/denoise.js'
import {
  SELECTION_INSTRUCTION,
  SELECTION_INSTRUCTION_RANGES,
  numberedTranscript,
  parseSelection,
  parseSelectionRanges,
} from './lib/selection.js'
import { messageText as projectMessageText } from './lib/projection.js'
import { canonicalJson, digest, loadEvidence, read as readEvidence, recordEvidence, sessionStore } from './lib/evidence.js'
import { eventAt } from './lib/session.js'
import { sha256Hex } from './lib/excerpts.js'
import { confirm as confirmInstall, loadOperations, recordOperation } from './lib/publication.js'
import { ResourceIO, checkEvidence } from './lib/resources.js'
import { UnderstandingStore } from './lib/understanding.js'

const { BasicCompactionEngine } = await loadDshPackage('@deepseek-ai/dsh-compaction-basic')
const { toolPairingBalancedBefore, isCompactCheckpointSource } = await loadDshPackage('@deepseek-ai/dsh-compaction')
const { BlockAssembler, createUserMessage } = await loadDshPackage('@deepseek-ai/dsh-llm')

const TOOL_NAME = 'compact_context'
const MAX_SELECTION_TOKENS = 4096

/**
 * Why the selective path fell back, kept on the ledger row.
 *
 * Headless runs swallow `logger.warn`, so a silent degradation used to be
 * invisible. The row is the only place a later reader can tell "the model chose
 * nothing" from "the request never finished" from "the JSON did not parse".
 */
const FALLBACK = {
  noProvider: 'no-provider',
  requestError: 'request-error',
  unfinished: 'unfinished',
  emptyOutput: 'empty-output',
  unusable: 'unusable-selection',
  rejected: 'checkpoint-rejected',
}


/** Custom message source: a labelled notice, not a user prompt. */
const NOTICE_SOURCE = { kind: 'wsc-compaction', form: 'notice', summary: 'Context pressure' }

const TOOL_DESCRIPTION_BASE =
  'Requests compaction of earlier conversation history. Execution happens at the next model-request boundary, ' +
  'so this call returns accepted/pending rather than a finished checkpoint. No arguments.'

/**
 * Compaction's effect on file state, stated as a capability fact.
 *
 * The checkpoint carries a bounded set of files, so a model that expects every
 * file to survive mis-plans. Stating the bound here — where the model reads
 * what the tool does — is a fact about the tool's effect, not advice about
 * when to call it. Only v2 keeps bodies, so v1 and `off` say nothing.
 *
 * @param {object|undefined} settings resolved wsc settings.
 * @returns {string} tool description.
 */
const describeTool = (settings) => {
  const workingset = settings?.workingset
  if (workingset === undefined || workingset === null) return TOOL_DESCRIPTION_BASE
  if ((workingset.version ?? 1) < 2) return TOOL_DESCRIPTION_BASE
  const parts = []
  if (Number.isInteger(workingset.maxFiles)) parts.push(`at most ${workingset.maxFiles} files`)
  if (Number.isInteger(workingset.capChars)) parts.push(`${workingset.capChars} characters each`)
  if (Number.isInteger(workingset.sectionCap)) parts.push(`${workingset.sectionCap} characters total`)
  const bounds = parts.length === 0 ? '' : ` (${parts.join(', ')})`
  return (
    `${TOOL_DESCRIPTION_BASE} The checkpoint carries the file state of the most recently touched files${bounds}; ` +
    'files outside that set are not carried, and reading them again returns their current content.'
  )
}

/**
 * Compaction backend whose ordinary trigger belongs to the model.
 *
 * Pressure at the warning line only publishes a factual notice; the hard line
 * compacts without asking. A successful `compact_context` call records one
 * pending request that the next `agent/pre-step` executes.
 */
export default class WscCompactionEngine extends BasicCompactionEngine {
  static inject = ['llm', 'tokenMeter', 'sessions', 'tools', 'wscConfig']

  constructor(ctx, config = {}) {
    super(ctx, { ...config, auto: false })
    this.pending = new WeakSet()
    this.notified = new WeakSet()
    this.toolAgents = new WeakSet()
    this.denoiseState = new WeakMap()
    this.#install()
  }

  /**
   * Per-session compaction telemetry, consumed by the ledger row.
   *
   * `selection` and `control` are recorded by the builder that ran; the ledger
   * handler merges them into the durable row and drops the entry, so one row
   * says both how much of the task survived and why the selective path did or
   * did not produce the checkpoint.
   */
  #telemetry = new Map()

  /**
   * The resolved payload policy is logged once per engine instance.
   *
   * A flag that never reaches the live path behaves exactly like a flag that
   * does nothing, and the difference is invisible from the results. One log
   * line naming the values the builder actually received turns that into a
   * fact the run record can be checked against.
   */
  #policyEchoed = false

  #echoPolicy(settings) {
    if (this.#policyEchoed) return
    this.#policyEchoed = true
    const p = settings.payload
    this.ctx.logger.info(
      `wsc policy: fraction=${p.sourceFraction} maxChars=${p.maxChars} quote=${p.quoteMaxChars} priorDepth=${p.priorEchoDepth} outputs=${p.outputsItems} outputsWeight=${p.outputsWeight} priorItemCap=${p.priorItemCap} workingset=${settings.workingset === undefined ? 'off' : `on(v${settings.workingset.version ?? 1},files=${settings.workingset.maxFiles},cap=${settings.workingset.capChars})`}`,
    )
  }

  #recordTelemetry(agent, patch) {
    const id = agent?.session?.id
    if (typeof id !== 'string') return
    const current = this.#telemetry.get(id) ?? {}
    // Merge in place: callers keep mutating the objects they handed over.
    Object.assign(current, patch)
    this.#telemetry.set(id, current)
  }

  #install() {
    const ctx = this.ctx

    // The engine lives in the preset's isolated compaction group, whose scope is
    // a child of the agent. A tool registered here would be invisible to the
    // model, so register it on each agent's own scoped context instead.
    ctx.on('agent/created', ({ agent }) => {
      try {
        this.#ensureTool(agent)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc compaction tool registration skipped: ${message}`)
      }
    })

    ctx.on('agent/pre-step', async ({ agent, signal }, next) => {
      try {
        this.#ensureTool(agent)
        await this.#consider(agent, signal)
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc compaction skipped: ${message}`)
      }
      return next()
    })

    this.#installDenoise()
    this.#installLedger()
  }

  /**
   * Side ledger for cost analysis: one JSONL row per durable compaction, read
   * from the committed summary event. It never writes session events.
   */
  #installLedger() {
    this.ctx.on('session/event', (session, event) => {
      if (event.type !== 'compaction/summary') return
      try {
        const home = process.env.DSH_HOME
        if (home === undefined || home === '') return
        const dir = join(home, 'wsc')
        mkdirSync(dir, { recursive: true })
        const data = event.data
        const summaryChars = Array.isArray(data.summary)
          ? data.summary.reduce((total, block) => total + (block.type === 'text' ? block.text.length : 0), 0)
          : 0

        // Shadow mode still compacts through the shipped backend; the candidate
        // is built here, never installed, so the two checkpoints can be compared.
        const settings = this.ctx.get('wscConfig')?.value
        const shadow = settings?.mode === 'shadow'
        let candidate = null
        if (shadow) {
          const messages = []
          for (const seq of data.shadowedSeqs ?? []) {
            const sourceEvent = eventAt(session, seq)
            if (sourceEvent === undefined) continue
            const message = session.deriveEventMessage(sourceEvent)
            if (message !== null && message !== undefined) messages.push(message)
          }
          const built = buildCheckpoint(
            { messages },
            {
              isCheckpointSource: (source) =>
                source !== undefined && source !== null && isCompactCheckpointSource(source),
              denoise: settings.denoise === true,
              controlItemCap: settings.controlItemCap,
              payload: settings.payload,
              workingset: settings.workingset,
              outputs: settings.outputs,
            },
          )
          candidate = {
            bytes: byteLength(built.text),
            sourceBytes: built.sourceBytes,
            verification: (built.text.match(/verified after that change/g) ?? []).length,
          }
        }

        const telemetry = this.#telemetry.get(session.id)
        if (telemetry !== undefined) this.#telemetry.delete(session.id)

        const record = {
          kind: shadow ? 'shadow' : 'compaction',
          at: new Date().toISOString(),
          sessionId: session.id,
          compactionId: data.compactionId,
          provider: data.provider,
          model: data.model,
          shadowedNodes: Array.isArray(data.shadowedSeqs) ? data.shadowedSeqs.length : 0,
          shadowedTokens: data.shadowedTokenCount,
          summaryChars,
          ...(candidate === null
            ? {}
            : {
                candidateBytes: candidate.bytes,
                candidateSourceBytes: candidate.sourceBytes,
                candidateVerification: candidate.verification,
              }),
          ...(telemetry === undefined
            ? {}
            : {
                control: telemetry.control ?? null,
                selection: telemetry.selection ?? null,
                payload: telemetry.payload ?? null,
              }),
          usage: data.usage ?? null,
        }
        // A summary is only accepted when it is bound to a package this engine
        // issued: same session, provider, model and summary digest. Anything
        // else is an unknown install and is reported rather than recorded.
        const packageDigest = sha256Hex(canonicalJson(Array.isArray(data.summary) ? data.summary : []))
        const operation = loadOperations(home, session.id).get(packageDigest)

        // Export the shadowed observations before anything is confirmed: the
        // bytes are fixed now, so a later read or lease can prove it returns
        // what was hidden rather than whatever the log holds at that moment.
        // A failed export is reported and leaves no locators behind.
        let locators = {}
        try {
          const io = new ResourceIO()
          for (const seq of data.shadowedSeqs ?? []) {
            const sourceEvent = eventAt(session, seq)
            if (sourceEvent === undefined) continue
            const message = session.deriveEventMessage(sourceEvent)
            if (message === null || message === undefined) continue
            const file = join(dir, 'evidence', session.id, `${seq}.json`)
            io.writeOnce(file, Buffer.from(canonicalJson(message)))
            locators[seq] = { file_path: file, sha256: digest(message) }
          }
          if (Object.keys(locators).length > 0) checkEvidence(io, { evidence: locators })
        } catch (error) {
          locators = {}
          this.ctx.logger.warn(`wsc evidence export: ${error.message}`)
        }
        let installed = false
        if (operation === undefined) {
          this.ctx.logger.warn(`wsc install: unknown_install ${packageDigest}`)
        } else {
          try {
            const done = confirmInstall(operation, {
              operationId: operation.id,
              packageDigest,
              sessionId: session.id,
              provider: data.provider,
              model: data.model,
              installedThrough: operation.package?.throughSeq,
              receiver: 'session-log',
              evidenceAccessible: true,
            })
            recordOperation(home, session.id, {
              id: done.id,
              state: done.state,
              at: new Date().toISOString(),
              receipt: done.receipt,
              ...(Object.keys(locators).length === 0 ? {} : { evidence: locators }),
            })
            installed = true
          } catch (error) {
            this.ctx.logger.warn(`wsc install: ${error.message}`)
          }
        }

        // The shadowed observations become evidence: each digest is fixed at the
        // moment of shadowing, so a later read can prove it returns the bytes
        // that were hidden rather than whatever the log holds now. Evidence is
        // only recorded for a confirmed install.
        if (installed) {
          recordEvidence(
            home,
            session.id,
            (data.shadowedSeqs ?? []).flatMap((seq) => {
              const sourceEvent = eventAt(session, seq)
              if (sourceEvent === undefined) return []
              const message = session.deriveEventMessage(sourceEvent)
              if (message === null || message === undefined) return []
              return [{ seq, digest: digest(message), bytes: byteLength(canonicalJson(message)) }]
            }),
          )
        }

        // Model-authored judgments become durable records, outside the
        // checkpoint text: each one keeps the refs it cited and the range it
        // was written for, and a later revision is a compare-and-swap.
        const judgments = operation.package?.judgments
        if (installed && Array.isArray(judgments) && judgments.length > 0) {
          try {
            const store = new UnderstandingStore({
              file: join(dir, 'understanding', `${session.id}.jsonl`),
            })
            // A replayed install must not turn one judgment into two revisions.
            const seen = new Set(
              store.all().map((record) => `${record.text}\u0000${JSON.stringify(record.scope)}`),
            )
            for (const judgment of judgments) {
              if (typeof judgment?.text !== 'string' || judgment.text.trim() === '') continue
              const scope = { session: session.id, shadowedSeqs: data.shadowedSeqs ?? [] }
              if (seen.has(`${judgment.text}\u0000${JSON.stringify(scope)}`)) continue
              store.write(
                {
                  text: judgment.text,
                  kind: 'judgment',
                  sources: Array.isArray(judgment.sources) ? judgment.sources : [],
                  scope,
                },
                { producer: 'selection' },
              )
            }
          } catch (error) {
            this.ctx.logger.warn(`wsc understanding skipped: ${error.message}`)
          }
        }

        appendFileSync(join(dir, 'compactions.jsonl'), `${JSON.stringify(record)}\n`, 'utf8')
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        this.ctx.logger.warn(`wsc ledger skipped: ${message}`)
      }
    })
  }

  /**
   * Runtime denoise: rewrite one tool result before it enters request history,
   * keeping the original retrievable through the spill store. Fail-open: a
   * missing backend or a storage error keeps the raw result inline.
   */
  #installDenoise() {
    const ctx = this.ctx

    ctx.on('tools/post-execute', async (exec, result, next) => {
      const decision = await next()
      try {
        if (decision.kind !== 'accept' || result.isError === true) return decision
        const settings = ctx.get('wscConfig')?.value
        if (settings?.denoise !== true) return decision
        const agent = exec.agent
        if (agent === undefined) return decision

        const content = decision.content ?? result.content
        const textBlocks = content.filter((block) => block.type === 'text')
        if (textBlocks.length === 0) return decision
        const text = textBlocks.map((block) => block.text).join('\n')
        if (text.length < 1200 || text.length > 50000) return decision

        let state = this.denoiseState.get(agent.session)
        if (state === undefined) {
          state = createDenoiseState()
          this.denoiseState.set(agent.session, state)
        }

        const outcome = runtimeDenoise(text, {
          toolName: exec.name,
          callId: exec.callId,
          args: exec.arguments,
          state,
        })
        if (outcome === null) return decision

        const pointer = await this.#spillOriginal(exec, text, outcome.rules)
        if (pointer === undefined) return decision

        return {
          ...decision,
          content: [
            { type: 'text', text: outcome.text + pointer },
            ...content.filter((block) => block.type !== 'text'),
          ],
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        ctx.logger.warn(`wsc denoise skipped: ${message}`)
        return decision
      }
    })
  }

  async #spillOriginal(exec, text, rules) {
    const spillStore = this.ctx.get('spillStore')
    if (spillStore === undefined) return undefined
    const sessionId = exec.agent?.session?.header?.id
    if (sessionId === undefined) return undefined
    try {
      const ref = await spillStore.saveText({
        owner: { sessionId },
        source: { kind: 'tool', toolName: exec.name, callId: exec.callId, label: 'result' },
        suggestedName: `${exec.name}.txt`,
        content: text,
      })
      const bytes = Buffer.byteLength(text, 'utf8')
      return `\n\n[denoise: ${rules.join(', ')}; original ${bytes} bytes at ${ref.locator}. ${ref.retrievalHint}]`
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.ctx.logger.warn(`wsc denoise could not preserve the original: ${message}`)
      return undefined
    }
  }

  #ensureTool(agent) {
    if (this.toolAgents.has(agent)) return
    this.toolAgents.add(agent)
    agent.ctx.tools.register({
      name: TOOL_NAME,
      description: describeTool(this.ctx.get('wscConfig')?.value),
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: { status: { type: 'string' } },
          required: ['status'],
        },
        render: (_args, value) => [
          {
            type: 'text',
            text: String((value && value.status) ?? 'compaction_request=accepted; execution=pending'),
          },
        ],
      },
      execute: async (_args, exec) => {
        if (exec.agent === undefined) throw new Error('compact_context requires an agent Session')
        this.pending.add(exec.agent.session)
        return { status: 'compaction_request=accepted; execution=pending' }
      },
    })

    if (this.ctx.get('wscConfig')?.value?.evidenceTool === false) return

    agent.ctx.tools.register({
      name: 'read_history',
      description:
        'Read earlier conversation events that were compacted away. Use seq to read one event by sequence number, ' +
        'or query to find literal text across the session history. Read-only.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          seq: { type: 'integer', description: 'Exact event sequence number to read.' },
          query: { type: 'string', description: 'Literal text to find in earlier events.' },
        },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: { text: { type: 'string' }, matches: { type: 'integer' } },
          required: ['text', 'matches'],
        },
        render: (_args, value) => [{ type: 'text', text: String((value && value.text) ?? '') }],
      },
      execute: async (args, exec) => {
        if (exec.agent === undefined) throw new Error('read_history requires an agent Session')
        const session = exec.agent.session

        const seq = Number(args?.seq)
        if (Number.isInteger(seq)) {
          const event = eventAt(session, seq)
          if (event === undefined) throw new Error(`read_history: no event at seq ${seq}`)
          const message = session.deriveEventMessage(event)
          const text = message === null || message === undefined ? `[${event.type}]` : fullText(message)
          return { text: clip(text, 6000), matches: 1 }
        }

        const query = typeof args?.query === 'string' ? args.query.trim() : ''
        if (query.length === 0) throw new Error('read_history requires seq or query')

        const lower = query.toLowerCase()
        const matches = []
        for (const event of session.events) {
          const message = session.deriveEventMessage(event)
          if (message === null || message === undefined) continue
          const text = messageText(message)
          const at = text.toLowerCase().indexOf(lower)
          if (at === -1) continue
          const start = Math.max(0, at - 80)
          matches.push(`#${event.seq} ${message.role}: ${clip(text.slice(start, at + query.length + 120), 260)}`)
          if (matches.length >= 8) break
        }

        return {
          text: matches.length === 0 ? `No event contains ${JSON.stringify(query)}.` : matches.join('\n'),
          matches: matches.length,
        }
      },
    })

    agent.ctx.tools.register({
      name: 'read_evidence',
      description:
        'Read exact bytes of one shadowed observation. seq must be an event that a compaction shadowed; the read ' +
        'returns canonical bytes, byte bounds and integrity hashes. offset and limit are bytes. Read-only.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          seq: { type: 'integer', description: 'Event sequence number of a shadowed observation.' },
          offset: { type: 'integer', description: 'Byte offset of the first byte to return.' },
          limit: { type: 'integer', description: 'Maximum number of bytes to return.' },
        },
        required: ['seq'],
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: {
            text: { type: 'string' },
            offset: { type: 'integer' },
            length: { type: 'integer' },
            total_bytes: { type: 'integer' },
            complete: { type: 'boolean' },
            read_sha256: { type: 'string' },
            object_sha256: { type: 'string' },
          },
          required: ['text', 'offset', 'length', 'total_bytes', 'complete', 'read_sha256', 'object_sha256'],
        },
        render: (_args, value) => [
          {
            type: 'text',
            text: value.complete
              ? String(value.text ?? '')
              : `${String(value.text ?? '')}\n[bytes ${value.offset}-${value.offset + value.length} of ${value.total_bytes}]`,
          },
        ],
      },
      execute: async (args, exec) => {
        if (exec.agent === undefined) throw new Error('read_evidence requires an agent Session')
        const session = exec.agent.session
        const seq = Number(args?.seq)
        if (!Number.isInteger(seq)) throw new Error('read_evidence requires an integer seq')
        const index = loadEvidence(process.env.DSH_HOME, session.id)
        const { store, access } = sessionStore(session, index, fullText)
        const result = readEvidence(store, access, seq, { offset: args?.offset, limit: args?.limit })
        return {
          text: result.content,
          offset: result.offset,
          length: result.length,
          total_bytes: result.total_bytes,
          complete: result.complete,
          read_sha256: result.read_sha256,
          object_sha256: result.object_sha256,
        }
      },
    })
  }

  /**
   * Produce the checkpoint. `selective` asks the model for verbatim quotes and
   * validates them; `deterministic` extracts by rule; `basic` delegates to the
   * shipped summarizer. A selective failure falls back to deterministic
   * extraction, so compaction never depends on one model answer.
   *
   * @param {{ messages: ReadonlyArray<object>, tools?: ReadonlyArray<object> }} input replayed region.
   * @param {object} agent owner of the session being compacted.
   * @param {AbortSignal | undefined} signal cancellation.
   * @returns {Promise<object>} summary blocks plus the producing identity.
   */
  async summarize(input, agent, signal) {
    const settings = this.ctx.get('wscConfig')?.value
    if (settings === undefined || settings.mode !== 'active') return super.summarize(input, agent, signal)

    this.#echoPolicy(settings)
    const checkpoint = await this.#summarizeCheckpoint(input, agent, signal, settings)
    this.#recordReady(checkpoint, agent)
    return checkpoint
  }

  /**
   * Record the package this engine is about to publish. The row is what makes a
   * later summary event verifiable: only a digest we issued can be confirmed.
   *
   * @param {object} checkpoint summary blocks plus the producing identity.
   * @param {object} agent owner of the session being compacted.
   */
  #recordReady(checkpoint, agent) {
    const home = process.env.DSH_HOME
    const sessionId = agent?.session?.id
    const blocks = checkpoint?.summary
    if (typeof home !== 'string' || home === '' || typeof sessionId !== 'string') return
    if (!Array.isArray(blocks) || blocks.length === 0) return
    const events = agent.session.events
    const throughSeq = events.length === 0 ? 0 : events[events.length - 1].seq
    const packageDigest = sha256Hex(canonicalJson(blocks))
    recordOperation(home, sessionId, {
      id: packageDigest,
      state: 'ready',
      at: new Date().toISOString(),
      package: {
        sessionId,
        provider: checkpoint.provider,
        model: checkpoint.model,
        throughSeq,
        packageDigest,
        judgments: Array.isArray(checkpoint.judgments) ? checkpoint.judgments : [],
      },
    })
  }

  async #summarizeCheckpoint(input, agent, signal, settings) {
    if (settings.selection === 'selective') {
      const selected = await this.#summarizeSelective(input, agent, signal, settings)
      if (selected !== null) return selected
    }
    if (settings.selection === 'basic') return super.summarize(input, agent, signal)

    return this.#summarizeDeterministic(input, agent, signal, settings)
  }

  async #summarizeDeterministic(input, agent, signal, settings) {
    const { text, sourceBytes, budget, control } = buildCheckpoint(input, {
      isCheckpointSource: (source) =>
        source !== undefined && source !== null && isCompactCheckpointSource(source),
      denoise: settings.denoise === true,
      controlItemCap: settings.controlItemCap,
      payload: settings.payload,
      workingset: settings.workingset,
      outputs: settings.outputs,
    })
    this.#recordTelemetry(agent, { control })
    if (text.length === 0 || byteLength(text) >= sourceBytes * 0.85) {
      return super.summarize(input, agent, signal)
    }

    this.ctx.logger.info(
      `wsc checkpoint: ${byteLength(text)} bytes (budget ${budget}) from ${sourceBytes} shadowed bytes`,
    )
    return {
      summary: [{ type: 'text', text }],
      provider: 'wsc',
      model: 'deterministic',
    }
  }

  async #summarizeSelective(input, agent, signal, settings) {
    const selection = {
      attempted: true,
      parsed: false,
      quotes: 0,
      spans: 0,
      fragments: 0,
      droppedAmbiguous: 0,
      droppedFacts: 0,
      hasOutput: false,
      finish: null,
      outputTokens: null,
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      fallbackReason: null,
    }
    this.#recordTelemetry(agent, { selection })

    const header = agent.session.requestHeader()?.config
    const provider = header?.provider ?? agent.options?.provider
    const model = header?.model ?? agent.options?.model
    if (typeof provider !== 'string' || typeof model !== 'string' || provider === '' || model === '') {
      selection.fallbackReason = FALLBACK.noProvider
      return null
    }

    const isCheckpointSource = (source) =>
      source !== undefined && source !== null && isCompactCheckpointSource(source)

    // Mandatory content is priced before the model call: when control messages
    // and prior checkpoints already exceed the view budget, no safe checkpoint
    // exists and the request must not be sent.
    const bound = mandatoryLowerBound(input, { isCheckpointSource })
    if (bound.mandatoryBytes >= bound.budget) {
      throw new Error(
        `wsc: mandatory view budget exhausted (${bound.mandatoryBytes} >= ${bound.budget} bytes)`,
      )
    }

    const assembler = new BlockAssembler()
    // Line addressing exists because output tokens are what a compaction
    // mostly spends: asking for quotes costs ~3.4k output tokens to keep ~550
    // tokens of text, asking for line numbers costs a few hundred.
    const rangeMode = settings.selectionAddress === 'lines'
    const instruction = rangeMode ? SELECTION_INSTRUCTION_RANGES : SELECTION_INSTRUCTION
    // The model can only address a message by name when the request shows the
    // same numbering the engine resolves against, so the region is projected as
    // a numbered transcript. Quotes are still verified against the original
    // bytes; the labels exist only inside this request.
    const transcript = numberedTranscript(input.messages, {
      toolText: settings.payload.toolText >= 1,
      lineNumbers: rangeMode,
    })
    const messages = transcript.addressable
      ? [
          {
            role: 'user',
            content: [
              { type: 'text', text: transcript.text },
              { type: 'text', text: instruction },
            ],
          },
        ]
      : [
          ...input.messages,
          { role: 'user', content: [{ type: 'text', text: instruction }] },
        ]
    const options = {
      provider,
      model,
      messages,
      ...(input.tools === undefined ? {} : { tools: [...input.tools] }),
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      sessionId: agent.session.id,
      purpose: 'compaction',
      ...(signal === undefined ? {} : { signal }),
    }

    try {
      for await (const chunk of this.ctx.llm.stream(options)) assembler.push(chunk)
    } catch (error) {
      if (signal?.aborted === true) throw error
      const message = error instanceof Error ? error.message : String(error)
      selection.fallbackReason = FALLBACK.requestError
      this.ctx.logger.warn(`wsc selection request failed: ${message}`)
      return null
    }

    const finish = assembler.finish
    selection.finish = finish?.kind ?? null
    selection.outputTokens = assembler.usage?.outputTokens ?? null
    if (finish !== undefined && (finish.kind === 'aborted' || finish.kind === 'error')) {
      if (signal?.aborted === true) throw new Error('wsc selection request aborted')
      selection.fallbackReason = FALLBACK.unfinished
      this.ctx.logger.warn('wsc selection request did not finish; using deterministic extraction')
      return null
    }

    const rawOutput = assembler.blocks()
    const text = rawOutput
      .filter((block) => block.type === 'text')
      .map((block) => block.text)
      .join('')
    selection.hasOutput = text.trim().length > 0
    const selectionResult = rangeMode ? parseSelectionRanges(text) : parseSelection(text)
    selection.address = rangeMode ? 'lines' : 'quotes'
    selection.ranges = selectionResult.ranges?.length ?? 0
    // The two parsers return different shapes: quotes mode carries quotes,
    // spans and fragments, line mode carries ranges. Read both through the same
    // optional accessors, or a range-mode result throws on a missing list and
    // the compaction never completes.
    selection.quotes = selectionResult.quotes?.length ?? 0
    selection.spans = selectionResult.spans?.length ?? 0
    selection.fragments = selectionResult.fragments?.length ?? 0
    if (
      selection.quotes === 0 &&
      selection.spans === 0 &&
      selection.fragments === 0 &&
      selection.ranges === 0
    ) {
      // Distinguishing "the model said nothing" from "it answered but the
      // object did not parse" is the whole point of the ledger field.
      selection.fallbackReason = selection.hasOutput ? FALLBACK.unusable : FALLBACK.emptyOutput
      this.ctx.logger.info('wsc selection returned no usable selection; using deterministic extraction')
      return null
    }

    const checkpoint = buildSelectiveCheckpoint(input, {
      quotes: selectionResult.quotes ?? [],
      facts: selectionResult.facts,
      ...(transcript.addressable
        ? {
            spans: selectionResult.spans ?? [],
            fragments: selectionResult.fragments ?? [],
            ranges: selectionResult.ranges ?? [],
          }
        : {}),
      toolText: settings.payload.toolText >= 1,
      isCheckpointSource,
      controlItemCap: settings.controlItemCap,
      payload: settings.payload,
      workingset: settings.workingset,
      outputs: settings.outputs,
    })
    if (
      checkpoint === null ||
      checkpoint.text.length === 0 ||
      byteLength(checkpoint.text) >= checkpoint.sourceBytes * 0.85
    ) {
      // Name the exact condition: "the model offered nothing usable" and "the
      // checkpoint was not smaller than its region" need different fixes, and
      // the ledger used to collapse both into one reason.
      selection.fallbackReason = FALLBACK.rejected
      selection.rejectedBecause =
        checkpoint === null
          ? 'no-quote-bound'
          : checkpoint.text.length === 0
            ? 'empty-text'
            : 'not-smaller'
      selection.offered =
        (selectionResult.quotes?.length ?? 0) +
        (selectionResult.fragments?.length ?? 0) +
        (selectionResult.ranges?.length ?? 0)
      return null
    }

    selection.parsed = true
    selection.droppedAmbiguous = checkpoint.droppedAmbiguous
    selection.droppedFacts = checkpoint.droppedFacts
    this.#recordTelemetry(agent, { control: checkpoint.control, payload: checkpoint.payload })

    this.ctx.logger.info(
      `wsc selective checkpoint: ${checkpoint.selectedCount} quotes ` +
        `(${checkpoint.droppedAmbiguous} ambiguous/missing dropped), ` +
        `${checkpoint.judgmentCount} judgments (${checkpoint.droppedFacts} unsourced dropped), ` +
        `${byteLength(checkpoint.text)} bytes from ${checkpoint.sourceBytes} shadowed bytes`,
    )
    return {
      summary: [{ type: 'text', text: checkpoint.text }],
      rawOutput,
      llmStreamCall: true,
      provider,
      model,
      maxTokens: settings.selectionMaxTokens ?? MAX_SELECTION_TOKENS,
      judgments: checkpoint.keptFacts ?? [],
      ...(assembler.usage === undefined ? {} : { usage: assembler.usage }),
    }
  }

  async #consider(agent, signal) {
    const settings = this.ctx.get('wscConfig')?.value
    if (settings === undefined || settings.mode === 'off') return

    const session = agent.session
    const target = routedTarget(session)
    if (target === undefined) return

    const info = await this.ctx.llm.resolveModelInfo(target.provider, target.model, signal)
    const capacity = info?.context?.contextWindow
    if (!Number.isInteger(capacity) || capacity <= 0) return

    const reserved = session.requestHeader()?.config?.maxTokens ?? info.defaultMaxTokens ?? 0
    const usable = capacity - Math.max(0, Math.trunc(reserved))
    if (usable <= 0) return

    // Capacity basis is mutually exclusive: a share of the usable window or a
    // fixed token cap. The inactive field is stored but never read.
    const budget =
      settings.capacityMode === 'tokens'
        ? Math.min(usable, Math.max(1024, Math.trunc(settings.capacityTokens)))
        : Math.max(1, Math.floor((usable * settings.capacityPercent) / 100))

    const measurement = this.ctx.tokenMeter.measure(session)
    const warnPercent = Math.round(settings.warnRatio * 100)
    const forcePercent = Math.round(settings.forceRatio * 100)
    const requested = this.pending.has(session)

    const timing = adjust(
      decide(measurement.totalTokens, budget, {
        modelRequested: requested,
        notified: this.notified.has(session),
        warnPercent,
        forcePercent,
      }),
      forcePercent,
    )

    if (settings.mode === 'shadow') {
      this.ctx.logger.info(
        `wsc shadow: ${usedPercent(timing.tokens, timing.capacity)}% ` +
          `(${timing.tokens}/${timing.capacity}), action=${timing.action}, notify=${timing.notify}`,
      )
    }

    if (timing.action === 'keep') {
      if (settings.mode === 'shadow') return
      if (measurement.totalTokens * 100 < budget * warnPercent) {
        this.notified.delete(session)
        return
      }
      if (!timing.notify) return
      this.notified.add(session)
      this.#notice(agent, timing, forcePercent)
      return
    }

    const retainTokens = Math.floor(budget * settings.retainRatio)

    // A request that cannot reclaim a meaningful share of the budget is a full
    // selection round trip for a few thousand tokens: the context regrows past
    // the trigger within a couple of steps and the run thrashes. The request is
    // consumed either way, so a skipped call does not stay pending.
    const admission = admitCompaction(timing, {
      budget,
      retainTokens,
      minReclaimRatio: settings.minReclaimRatio ?? 0,
    })
    if (!admission.admit) {
      this.pending.delete(session)
      this.ctx.logger.info(
        `wsc compaction skipped (${timing.action}): reclaim ~${admission.reclaimTokens} tokens ` +
          `is below the ${admission.floor}-token floor`,
      )
      return
    }

    const range = selectCompactableRange(session, measurement, retainTokens, toolPairingBalancedBefore)
    if (range === null) return

    this.pending.delete(session)
    this.notified.delete(session)

    const result = await this.compactRegion(range.start, range.end, agent, signal)
    this.ctx.logger.info(
      `wsc compaction (${timing.action}): shadowed ${result.shadowedSeqs.length} surface nodes, ` +
        `~${result.shadowedTokenCount} tokens (reclaim ~${admission.reclaimTokens}, ${admission.reason})`,
    )
  }

  #notice(agent, timing, forcePercent) {
    const percent = usedPercent(timing.tokens, timing.capacity)
    const text = `Context pressure ${percent}% (${timing.tokens} / ${timing.capacity} tokens). Forced compaction at ${forcePercent}% of capacity; compact_context triggers compaction on request.`
    agent.inject(
      createUserMessage({
        content: [{ type: 'text', text }],
        source: { ...NOTICE_SOURCE, summary: `Context pressure ${percent}%` },
      }),
    )
  }
}

/** History and evidence reads show tool output: it is the region's content. */
const fullText = (message) => projectMessageText(message, { toolText: true, toolCalls: true })

function clip(text, max) {
  const value = String(text ?? '')
  return value.length <= max ? value : `${value.slice(0, max)}…`
}


function routedTarget(session) {
  const config = session.requestHeader()?.config
  if (config === undefined || config.provider.length === 0 || config.model.length === 0) return undefined
  return { provider: config.provider, model: config.model }
}
