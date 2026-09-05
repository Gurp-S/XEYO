import {useEffect} from 'react';
import {useLocation} from 'react-router-dom';
import {pageViewFromPath} from '@/lib/appNav';
import {useNavJournalStore} from '@/stores/navJournalStore';

/**
 * 全局导航历史采集：路由（含 search）变化时记入 navJournalStore。
 * 页面视图状态已并入路由（/usage、/plugins），usageOpen 由路径派生
 * （2026-09-05 复用审计 ④，不再依赖 settingsStore）。幂等；HMR/StrictMode 重复触发无副作用。
 */
export function NavJournalSync() {
	const location = useLocation();
	useEffect(() => {
		useNavJournalStore.getState().record({
			path: `${location.pathname}${location.search}`,
			usageOpen: pageViewFromPath(location.pathname) === 'usage',
		});
	}, [location.pathname, location.search]);
	return null;
}
