import {useSettingsStore} from '@/stores/settingsStore';
import {MemorySwitchesSetting} from '../MemorySwitchesSetting';
import {Switch} from '../ui/Switch';

export function BehaviorSettings() {
	const maxBudgetUsd = useSettingsStore(s => s.maxBudgetUsd);
	const searxngUrl = useSettingsStore(s => s.searxngUrl ?? '');
	const outputCompact = useSettingsStore(s => s.outputCompact === true);
	const outputMode = useSettingsStore(s => s.outputMode ?? 'lite');
	const codeCompact = useSettingsStore(s => s.codeCompact === true);
	const codeMode = useSettingsStore(s => s.codeMode ?? 'lite');
	const update = useSettingsStore(s => s.update);
	return <section className="xy-behavior-settings space-y-5">
		<h3 className="xy-section-label">对话与工具</h3>
		<label className="block text-sm">单次对话预算（USD）<input className="xy-settings-input" type="number" min={0} step="0.001" value={maxBudgetUsd} onChange={e => update({maxBudgetUsd:e.target.value})} placeholder="留空为不限"/><small>按服务商返回的用量累计，达到上限后停止本轮。</small></label>
		<label className="block text-sm">SearXNG 地址<input className="xy-settings-input" type="url" value={searxngUrl} onChange={e => update({searxngUrl:e.target.value})} placeholder="http://127.0.0.1:8080"/><small>可选。填写自建搜索服务的地址。</small></label>
		{([{key:'output',label:'输出精简',description:'控制回答的精简程度。',checked:outputCompact,mode:outputMode}, {key:'code',label:'写代码精简',description:'控制生成代码的精简程度。',checked:codeCompact,mode:codeMode}] as const).map(item => <div key={item.key} className="xy-setting-group">
			<div className="xy-setting-row"><div><strong>{item.label}</strong><p>{item.description}</p></div><Switch label={item.label} checked={item.checked} onChange={() => update(item.key === 'output' ? {outputCompact:!item.checked} : {codeCompact:!item.checked})}/></div>
			{item.checked && <label className="xy-setting-row">精简程度<select aria-label={`${item.label}模式`} value={item.mode} onChange={e => {const mode=e.target.value as 'lite'|'full'|'ultra';update(item.key === 'output' ? {outputMode:mode} : {codeMode:mode});}}><option value="lite">Lite · 轻度</option><option value="full">Full · 精简</option><option value="ultra">Ultra · 极简</option></select></label>}
		</div>)}
		<div className="xy-setting-group"><h3 className="xy-section-label">上下文与记忆</h3><MemorySwitchesSetting/></div>
	</section>;
}
