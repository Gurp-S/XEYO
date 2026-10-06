import {useEffect, useRef, useState} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {useChatUiStore} from '@/stores/chatUiStore';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
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
		// 退出沉浸：让常驻的基础 Composer 按共享草稿重载。基础输入框在沉浸期间
		// 只是被盖住、并未卸载，不重载就会保留进场前的陈旧值——随后任一敲键都会
		// 把沉浸期间续写的内容整段顶掉（静默丢字）。
		return () => {
			const st = useChatStore.getState();
			const sid = st.activeId;
			if (sid) {
				st.requestComposerDraftRestore(sid);
			}
		};
	}, []);

	// 沉浸层自己的 Esc 归 escStack（LIFO，一键只关一层）：面板开着先关面板、再退沉浸。
	// 裸 window 监听会与下层注入口（如正在编辑的消息气泡、编辑层）同按一键、连关两层。
	useEffect(() => {
		pushEscLayer('immersive-layer', () => setImmersive(false));
		return () => popEscLayer('immersive-layer');
	}, [setImmersive]);

	useEffect(() => {
		if (!panelOpen) {
			return;
		}
		pushEscLayer('immersive-panel', () => setPanelOpen(false));
		return () => popEscLayer('immersive-panel');
	}, [panelOpen]);

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
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, []);

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
	// 与 Composer 的模型弹层同款配对：外点关闭 + Esc 层。沉浸版此前两者都缺：
	// 弹层打开后只能再点一次按钮才关，按 Esc 反而把整块侧板关掉。
	useEffect(() => {
		if (!open) {
			return;
		}
		const onDoc = (e: MouseEvent) => {
			const target = e.target as Node;
			if (btnRef.current?.contains(target)) {
				return;
			}
			// 弹层是 portal 到 body 的：命中弹层自身（id=menuId）不算外点。
			if (document.getElementById('immersive-model-picker')?.contains(target)) {
				return;
			}
			setOpen(false);
		};
		pushEscLayer('immersive-model', () => setOpen(false));
		document.addEventListener('mousedown', onDoc);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			popEscLayer('immersive-model');
		};
	}, [open]);
	return (
		<div className="relative">
			<button
				ref={btnRef}
				type="button"
				className="xy-press flex items-center gap-2 rounded-full border border-[var(--xy-imm-chip-line)] bg-[var(--xy-imm-chip-bg)] px-3 py-1.5 text-[13px] text-[var(--xy-imm-fg-strong)] backdrop-blur hover:bg-[var(--xy-imm-chip-bg-hover)]"
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