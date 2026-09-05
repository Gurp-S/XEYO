import {useEffect} from 'react';
import {useLocation} from 'react-router-dom';
import {useSettingsStore} from '@/stores/settingsStore';
import {useNavJournalStore} from '@/stores/navJournalStore';

/**
 * 全局导航历史采集：路由（含 search）与用量面板开合变化时
 * 记入 navJournalStore。幂等；HMR/StrictMode 重复触发无副作用。
 */
export function NavJournalSync() {
	const location = useLocation();
	const usagePanelOpen = useSettingsStore(s => s.usagePanelOpen);
	useEffect(() => {
		useNavJournalStore.getState().record({
			path: `${location.pathname}${location.search}`,
			usageOpen: usagePanelOpen,
		});
	}, [location.pathname, location.search, usagePanelOpen]);
	return null;
}
