import {BarChart3, Blocks, Home, Settings, ShieldCheck} from 'lucide-react';
import {useLocation} from 'react-router-dom';
import {closePageView, openPageView, pageViewFromPath} from '@/lib/appNav';
import {useSettingsStore} from '@/stores/settingsStore';

export function ActivityRail() {
	const location = useLocation();
	const page = pageViewFromPath(location.pathname);
	return <nav className="xy-activity-rail" aria-label="应用导航">
		<button aria-label="对话" title="对话" aria-pressed={!page} onClick={() => closePageView()}><Home size={18} /></button>
		{([{id:'usage', name:'用量', Icon:BarChart3}, {id:'plugins',name:'扩展',Icon:Blocks}, {id:'diagnostics',name:'诊断',Icon:ShieldCheck}] as const).map(({id,name,Icon}) => <button key={id} aria-label={name} title={name} aria-pressed={page===id} onClick={() => page===id ? closePageView() : openPageView(id)}><Icon size={20} /></button>)}
		<span className="xy-rail-spacer" /><button aria-label="设置" title="设置" onClick={() => useSettingsStore.getState().openSettings()}><Settings size={18} /></button>
	</nav>;
}
