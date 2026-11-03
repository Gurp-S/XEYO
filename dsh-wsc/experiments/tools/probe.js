// Throwaway probe: record which agent/session events reach the host context,
// and how the token measurement moves step to step.
//
// Writes one JSON line per observation to DSH_HOME/probe/events.jsonl.
import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

const HOME = process.env.DSH_HOME ?? ''
const DIR = join(HOME, 'probe')

const record = (kind, extra = {}) => {
  try {
    mkdirSync(DIR, { recursive: true })
    appendFileSync(join(DIR, 'events.jsonl'), `${JSON.stringify({ kind, at: Date.now(), ...extra })}\n`)
  } catch {
    // A probe must never disturb the run under test.
  }
}

export function apply(ctx) {
  record('apply')

  // The engine reports its own bail-outs through the logger, and headless runs
  // print no log lines. Mirror them into the probe log to see why it declines.
  try {
    const logger = ctx.logger
    for (const level of ['warn', 'info', 'debug']) {
      const original = logger[level]?.bind(logger)
      if (original === undefined) continue
      logger[level] = (...args) => {
        record('log', { level, message: args.map((arg) => (typeof arg === 'string' ? arg : JSON.stringify(arg))).join(' ') })
        return original(...args)
      }
    }
    record('log-hooked')
  } catch (error) {
    record('log-hook-failed', { message: error.message })
  }

  let meter
  ctx.inject(['tokenMeter'], (child) => {
    meter = child.tokenMeter
    record('token-meter', { ctor: meter?.constructor?.name ?? null })
  })

  // `agent/pre-step` is a waterfall: a plain listener would swallow the chain.
  ctx.on('agent/pre-step', (payload, next) => {
    const agent = payload?.agent
    let tokens
    try {
      tokens = meter?.measure(agent.session)?.totalTokens
    } catch (error) {
      tokens = `throw:${error.message}`
    }
    record('agent/pre-step', { step: payload?.step, tokens })
    return next()
  })

  ctx.on('session/event', (session, event) => {
    if (typeof event?.type === 'string' && event.type.startsWith('compaction')) {
      record('compaction-event', { type: event.type })
    }
  })
}

export const name = 'wsc-probe'
