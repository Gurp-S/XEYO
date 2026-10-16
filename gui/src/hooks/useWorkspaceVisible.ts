import {useLocation} from 'react-router-dom';
import {pageViewFromPath} from '@/lib/appNav';
import {useSettingsStore} from '@/stores/settingsStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

/** Keep drafts mounted, but stop background work while another page covers them. */
export function useWorkspaceVisible() {
	const open=useWorkspaceStore(s=>s.open);
	const settings=useSettingsStore(s=>s.settingsModalOpen);
	const location=useLocation();
	return open && !settings && !pageViewFromPath(location.pathname);
}
