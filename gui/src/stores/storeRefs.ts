import type {WorkspaceTool} from './workspaceStore';

/** Late-bound workspace accessor — breaks explorerStore → api → chatStream → workspaceStore cycle. */
let workspaceGetState: (() => {activeTool: WorkspaceTool | null}) | null = null;

export function registerWorkspaceAccessor(
	getState: () => {activeTool: WorkspaceTool | null},
): void {
	workspaceGetState = getState;
}

export function workspaceActiveTool(): WorkspaceTool | null {
	return workspaceGetState?.().activeTool ?? null;
}
