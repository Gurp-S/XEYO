window.__ModuleLoader__.load({
  id: '@xeyo/dsh-wsc',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const NS = 'wsc'
    const ENTRY = 'wsc-config'

    const DICT = {
      en: {
        nav: 'Context compaction',
        title: 'Context compaction',
        intro: 'WSC replaces the shipped summarizer inside the active agent preset. Values below are live.',
        mode: 'Mode',
        modeActive: 'Active',
        modeShadow: 'Shadow (measure only)',
        modeOff: 'Off',
        capacityMode: 'Capacity basis',
        modeRatio: 'Share of context window',
        modeTokens: 'Fixed token count',
        capacityPercent: 'Window share (%)',
        capacityTokens: 'Token cap',
        warn: 'Warning threshold',
        force: 'Forced compaction',
        retain: 'Retained tail',
        selection: 'Checkpoint source',
        selectionDeterministic: 'Deterministic extraction',
        selectionBasic: 'Model summary (shipped)',
        selectionSelective: 'Model selection (verbatim quotes)',
        denoise: 'Denoise tool output',
        evidence: 'History retrieval tool',
        hint: 'Capacity basis is exclusive. Warning and forced compaction are fractions of the chosen capacity.',
        unavailable: 'This profile does not serve the WSC configuration.',
        saved: 'Saved',
        failed: 'Not saved',
      },
      zh: {
        nav: '上下文压缩',
        title: '上下文压缩',
        intro: 'WSC 替换当前 agent preset 里的摘要器，下面的值即时生效。',
        mode: '模式',
        modeActive: '启用',
        modeShadow: '影子（只测量）',
        modeOff: '关闭',
        capacityMode: '容量口径',
        modeRatio: '按窗口占比',
        modeTokens: '按固定 token 数',
        capacityPercent: '窗口占比（%）',
        capacityTokens: 'Token 上限',
        warn: '警告阈值',
        force: '强制压缩阈值',
        retain: '保留尾部比例',
        selection: '检查点来源',
        selectionDeterministic: '确定性抽取',
        selectionBasic: '模型摘要（官方）',
        selectionSelective: '模型选材（逐字引用）',
        denoise: '工具输出去噪',
        evidence: '历史回读工具',
        hint: '容量口径二选一；警告和强制压缩按所选上限的比例计算。',
        unavailable: '当前 profile 没有提供 WSC 配置。',
        saved: '已保存',
        failed: '未保存',
      },
    }

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

    const readSnapshot = (form) => {
      try {
        return form === undefined ? undefined : form.getSnapshot()
      } catch {
        return undefined
      }
    }

    const styles = {
      page: { padding: '8px 0 24px', display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 640 },
      title: { color: 'var(--dsw-alias-label-primary)', fontSize: 16, fontWeight: 500, margin: '0 0 4px' },
      intro: { color: 'var(--dsw-alias-label-secondary)', fontSize: 13, lineHeight: '20px', margin: '0 0 12px' },
      row: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        padding: '10px 0',
        borderBottom: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.18))',
      },
      label: { color: 'var(--dsw-alias-label-primary)', fontSize: 14 },
      hint: { color: 'var(--dsw-alias-label-secondary)', fontSize: 12, lineHeight: '18px', marginTop: 12 },
      control: {
        color: 'var(--dsw-alias-label-primary)',
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.3))',
        borderRadius: 6,
        padding: '4px 8px',
        fontSize: 13,
        minWidth: 160,
      },
      number: {
        color: 'var(--dsw-alias-label-primary)',
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.3))',
        borderRadius: 6,
        padding: '4px 8px',
        fontSize: 13,
        width: 96,
        textAlign: 'right',
      },
    }

    function Row({ label, children }) {
      return h('div', { style: styles.row }, h('span', { style: styles.label }, label), children)
    }

    function Page(props) {
      const form = props.form
      const t = props.t
      const [snapshot, setSnapshot] = React.useState(() => readSnapshot(form))
      const [status, setStatus] = React.useState('')

      React.useEffect(() => {
        if (form === undefined || typeof form.subscribe !== 'function') return undefined
        return form.subscribe(() => setSnapshot(readSnapshot(form)))
      }, [form])

      if (snapshot === undefined || snapshot.value === undefined) {
        return h('div', { style: styles.page }, h('div', { style: styles.intro }, t('unavailable')))
      }

      const value = snapshot.value
      const write = (key, next) => {
        if (form === undefined || typeof form.mutate !== 'function') return
        setStatus('')
        Promise.resolve(form.mutate([{ op: 'set', path: [key], value: next }]))
          .then(() => setStatus('saved'))
          .catch(() => setStatus('failed'))
      }

      const mode = h(
        'select',
        { style: styles.control, value: value.mode ?? 'active', onChange: (event) => write('mode', event.target.value) },
        h('option', { value: 'active' }, t('modeActive')),
        h('option', { value: 'shadow' }, t('modeShadow')),
        h('option', { value: 'off' }, t('modeOff')),
      )

      const selection = h(
        'select',
        {
          style: styles.control,
          value: value.selection ?? 'selective',
          onChange: (event) => write('selection', event.target.value),
        },
        h('option', { value: 'deterministic' }, t('selectionDeterministic')),
        h('option', { value: 'basic' }, t('selectionBasic')),
        h('option', { value: 'selective' }, t('selectionSelective')),
      )

      const number = (key, min, max, step = 0.01, disabled = false) =>
        h('input', {
          style: styles.number,
          type: 'number',
          min,
          max,
          step,
          disabled,
          defaultValue: value[key],
          onBlur: (event) => {
            const parsed = Number(event.target.value)
            if (Number.isFinite(parsed)) write(key, clamp(parsed, min, max))
          },
        })

      const tokenMode = value.capacityMode === 'tokens'
      const capacityMode = h(
        'div',
        { style: { display: 'flex', gap: 12, alignItems: 'center' } },
        h(
          'label',
          { style: styles.label },
          h('input', {
            type: 'radio',
            checked: !tokenMode,
            onChange: () => write('capacityMode', 'ratio'),
          }),
          ` ${t('modeRatio')}`,
        ),
        h(
          'label',
          { style: styles.label },
          h('input', {
            type: 'radio',
            checked: tokenMode,
            onChange: () => write('capacityMode', 'tokens'),
          }),
          ` ${t('modeTokens')}`,
        ),
      )

      return h(
        'div',
        { style: styles.page },
        h('h2', { style: styles.title }, t('title')),
        h('p', { style: styles.intro }, t('intro')),
        h(Row, { label: t('mode') }, mode),
        h(Row, { label: t('capacityMode') }, capacityMode),
        h(Row, { label: t('capacityPercent') }, number('capacityPercent', 1, 100, 1, tokenMode)),
        h(Row, { label: t('capacityTokens') }, number('capacityTokens', 1024, 10000000, 1, !tokenMode)),
        h(Row, { label: t('warn') }, number('warnRatio', 0.5, 0.95)),
        h(Row, { label: t('force') }, number('forceRatio', 0.5, 0.99)),
        h(Row, { label: t('retain') }, number('retainRatio', 0, 0.5)),
        h(Row, { label: t('selection') }, selection),
        h(
          Row,
          { label: t('denoise') },
          h('input', {
            type: 'checkbox',
            checked: value.denoise === true,
            onChange: (event) => write('denoise', event.target.checked),
          }),
        ),
        h(
          Row,
          { label: t('evidence') },
          h('input', {
            type: 'checkbox',
            checked: value.evidenceTool !== false,
            onChange: (event) => write('evidenceTool', event.target.checked),
          }),
        ),
        h('p', { style: styles.hint }, t('hint')),
        status === '' ? null : h('p', { style: styles.hint }, t(status)),
      )
    }

    return {
      inject: ['slots', 'locale', 'configForms'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, DICT), 'wsc: dictionaries')
        const t = ctx.locale.bind(NS)

        ctx.slots.inject('settings.section', () =>
          ctx.slots.register(
            {
              name: 'settings.section',
              id: 'wsc',
              order: 25,
              label: () => t('nav'),
              locale: NS,
              inject: () => {
                let form
                try {
                  form = ctx.configForms.get(ENTRY)
                } catch {
                  form = undefined
                }
                return { form, t }
              },
            },
            Page,
          ),
        )
      },
    }
  },
})
