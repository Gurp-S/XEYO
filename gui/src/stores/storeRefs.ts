import type {WorkspaceTool} from './workspaceStore';

/** 延迟绑定的 workspace 访问器——打破 explorerStore → api → chatStream → workspaceStore 循环依赖。 */
let workspaceGetState: (() => {activeTool: WorkspaceTool | null}) | null = null;

export function registerWorkspaceAccessor(
	getState: () => {activeTool: WorkspaceTool | null},
): void {
	workspaceGetState = getState;
}

export function workspaceActiveTool(): WorkspaceTool | null {
	return workspaceGetState?.().activeTool ?? null;
}
