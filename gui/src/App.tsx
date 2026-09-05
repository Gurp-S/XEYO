import {Suspense, lazy} from 'react';
import {BrowserRouter, Navigate, Route, Routes} from 'react-router-dom';
import {CommandPalette} from '@/components/CommandPalette';
import {GuiErrorBoundary} from '@/components/GuiErrorBoundary';
import {ToastHost} from '@/components/ToastHost';
import {NavJournalSync} from '@/components/NavJournalSync';
import {ContextMenuHost} from '@/components/ui/ContextMenu';
import {ChatPage} from '@/pages/ChatPage';

function LazyOfflineReplayRoute() {
	const OfflineReplayRoute = lazy(() =>
		import('@/bench/OfflineReplayRoute').then(m => ({
			default: m.OfflineReplayRoute,
		})),
	);
	return (
		<Suspense fallback={null}>
			<OfflineReplayRoute />
		</Suspense>
	);
}

function LazyFadeLabRoute() {
	const FadeLabRoute = lazy(() =>
		import('@/bench/FadeLabRoute').then(m => ({
			default: m.FadeLabRoute,
		})),
	);
	return (
		<Suspense fallback={null}>
			<FadeLabRoute />
		</Suspense>
	);
}

export default function App() {
	return (
		<GuiErrorBoundary>
			<BrowserRouter>
			<Routes>
				{import.meta.env.DEV ? (
					<Route path="/bench/chat" element={<LazyOfflineReplayRoute />} />
				) : null}
				{import.meta.env.DEV ? (
					<Route path="/bench/fade" element={<LazyFadeLabRoute />} />
				) : null}
				<Route path="/" element={<ChatPage />} />
				<Route path="/c/:sessionId" element={<ChatPage />} />
				<Route path="/side/:sessionId" element={<ChatPage />} />
				<Route path="*" element={<Navigate to="/" replace />} />
			</Routes>
			{/* 全局 Toast 宿主：路由之外，仅挂载一次 */}
			<ToastHost />
			{/* 全局右键菜单宿主：路由之外，仅挂载一次 */}
			<ContextMenuHost />
			{/* 全局命令面板：Ctrl+K */}
			<CommandPalette />
			{/* 全局导航历史采集：整个 GUI 的 上一个/下一个界面（侧栏右上角箭头） */}
			<NavJournalSync />
		</BrowserRouter>
		</GuiErrorBoundary>
	);
}
