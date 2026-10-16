import type {WorkspaceTool} from '@/stores/workspaceStore';
export const TOOL_WIDTH_DEFAULT = 560;
export function clampToolWidth(value: unknown): number {
 return typeof value === 'number' && Number.isFinite(value) ? Math.min(960, Math.max(480, Math.round(value))) : TOOL_WIDTH_DEFAULT;
}
export function workbenchLayout(tool: WorkspaceTool | null, host: number, fileWidth: number, toolWidth: number) {
 const wide = tool === 'terminal' || tool === 'browser' || tool === 'map';
 const focused = wide && host < 820;
 return {wide, focused, width: wide ? Math.min(clampToolWidth(toolWidth), Math.max(0, host - 340)) : fileWidth};
}
