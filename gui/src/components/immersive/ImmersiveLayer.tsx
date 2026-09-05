import {useEffect, useRef, useState} from 'react';
import {useChatUiStore} from '@/stores/chatUiStore';
import {useSettingsStore} from '@/stores/settingsStore';
import {Composer} from '@/components/Composer';
import {MessageList} from '@/components/MessageList';
import {ModelPicker} from '@/components/ModelPicker';
import {ImmersiveClock} from './ImmersiveClock';
import {ImmersiveSidePanel, ImmersiveSidePanelHandle} from './ImmersiveSidePanel';

/**
 * 沉浸层（smoke-test #5 重做）：
 * - 顶部条去除（ImmersiveHeader 删除）；功能与会话标题迁入右侧板（ImmersiveSidePanel）。
 * - 右侧板可手动 toggle（按钮 + `Ctrl/Cmd+B` 快捷键）；`Esc` 逐层退出（右板开则关，否则退沉浸）。
 * - 进入/退出沉浸态时右板开合重置为「默认开」（ImmersiveLayer 重 mount 即重置 local state）。
 */
export function ImmersiveLayer() {
	const bgImage = useSettingsStore(s => s.bgImage);
	const setImmersive = useChatUiStore(s => s.setImmersive);
	const [panelOpen, setPanelOpen] = useState(true);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (
				(e.ctrlKey || e.metaKey) &&
				!e.shiftKey &&
				!e.altKey &&
				e.key.toLowerCase() === 'b'
			) {
				e.preventDefault();
				setPanelOpen(v => !v);
				return;
			}
			if (e.key === 'Escape') {
				if (panelOpen) {
					e.preventDefault();
					setPanelOpen(false);
					return;
				}
				e.preventDefault();
				setImmersive(false);
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [panelOpen, setImmersive]);

	return (
		<div className="xy-immersive fixed inset-0 z-[100] overflow-hidden">
			{bgImage ? (
				<div
					aria-hidden
					className="xy-immersive-bg absolute inset-0 z-0"
					style={{backgroundImage: `url(${bgImage})`}}
				/>
			) : null}
			<div aria-hidden className="xy-immersive-veil absolute inset-0 z-0" />

			{panelOpen ? (
				<ImmersiveSidePanel onCollapse={() => setPanelOpen(false)} />
			) : (
				<ImmersiveSidePanelHandle onExpand={() => setPanelOpen(true)} />
			)}

			<div className="absolute left-6 top-1/2 z-20 -translate-y-1/2">
				<ImmersiveModelPicker />
			</div>
			<div className="absolute bottom-6 left-6 z-20">
				<ImmersiveClock />
			</div>

			<div className="relative z-10 flex h-full min-h-0 flex-col">
				<div className="mx-auto flex h-full w-full max-w-3xl min-h-0 flex-1 flex-col px-4 pt-10 pb-2">
					<MessageList />
					<Composer showTodoDock={false} />
				</div>
			</div>
		</div>
	);
}

function ImmersiveModelPicker() {
	const model = useSettingsStore(s => s.model);
	const [open, setOpen] = useState(false);
	const btnRef = useRef<HTMLButtonElement>(null);
	return (
		<div className="relative">
			<button
				ref={btnRef}
				type="button"
				className="xy-press flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[13px] text-white/90 backdrop-blur hover:bg-white/10"
				aria-haspopup="menu"
				aria-expanded={open}
				onClick={() => setOpen(v => !v)}
			>
				<span aria-hidden>✦</span>
				<span className="max-w-40 truncate">{model}</span>
			</button>
			<ModelPicker
				open={open}
				menuId="immersive-model-picker"
				portal
				anchorRef={btnRef}
			/>
		</div>
	);
}