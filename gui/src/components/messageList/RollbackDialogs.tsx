/**
 * 回溯弹窗：仅 v3 热路径（RewindV3Dialog）。
 * V2 WorkspaceRevertDialog 确认/blocked/recovery/resend 已从主路径拆除。
 */
import {RewindV3Dialog} from '../WorkspaceRevertDialog';

export type RollbackDialogsProps = {
	activeSessionId: string | null;
};

export function RollbackDialogs({activeSessionId}: RollbackDialogsProps) {
	if (!activeSessionId) {
		return null;
	}
	return <RewindV3Dialog sessionId={activeSessionId} />;
}
