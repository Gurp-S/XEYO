import {ChevronDown, ShieldAlert, ShieldCheck, ShieldQuestion} from 'lucide-react';
import {useEffect, useRef, useState} from 'react';

import {setSessionRuntimeMode} from '@/lib/api/runtimeMode';
import {patchComposerDraftModes} from '@/lib/composerDrafts';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';
import {useDismiss} from '@/ui/useDismiss';
import {useChatUiStore} from '@/stores/chatUiStore';
import {useSettingsStore, type PermissionMode} from '@/stores/settingsStore';

const MODES: {
	mode: PermissionMode;
	label: string;
	desc: string;
	Icon: typeof ShieldCheck;
	danger?: boolean;
}[] = [
	{
		mode: 'always',
		label: '请求批准',
		desc: '编辑/写入、外发与网络访问每次都需批准',
		Icon: ShieldQuestion,
	},
	{
		mode: 'risk',
		label: '帮我批准',
		desc: '只读命令与工作区内安全写自动放行；仅对风险操作请求批准',
		Icon: ShieldCheck,
	},
	{
		mode: 'never',
		label: '完全访问权限',
		desc: '工作区内外部读写均免确认（含越出工作区找日志）；密钥、策略文件、受保护元数据与危险命令仍硬拦',
		Icon: ShieldAlert,
		danger: true,
	},
];

export function ApprovalModeButton() {
	const mode = useSettingsStore(s => s.permissionMode);
	const update = useSettingsStore(s => s.update);
	const activeId = useChatUiStore(s => s.activeId);
	const [open, setOpen] = useState(false);
	// 非空 = 这一档只是用户点的意图，本会话的引擎还没认账（写失败/回执不符）。
	// 不滚回本地选择：没有活值的会话里，请求 body 才是生效通道，滚回去等于把
	// 用户要的档位改回旧档。诚实做法是"照你说的显示，但标出没确认"。
	const [unconfirmed, setUnconfirmed] = useState('');
	const seq = useRef(0);
	const rootRef = useRef<HTMLDivElement | null>(null);

	// 换会话：上一枪的回执属于别的会话，提示不能跟着搬。
	useEffect(() => {
		seq.current += 1;
		setUnconfirmed('');
	}, [activeId]);

	// 关闭配对：Esc 走 escStack（优先于「停止生成」等下层）+ 外点关闭。
	useDismiss({open, onClose: () => setOpen(false), escId: 'approval-mode', keepOpenRefs: [rootRef]});

	const current = MODES.find(m => m.mode === mode) ?? MODES[1];
	const CurrentIcon = current.Icon;

	const selectMode = (next: PermissionMode) => {
		const mySeq = ++seq.current;
		update({permissionMode: next});
		setUnconfirmed('');
		setOpen(false);
		if (!activeId) {
			return;
		}
		patchComposerDraftModes(activeId, {permissionMode: next});
		// 立即写活状态：同一轮内尚未执行的下一工具调用即按新模式判定。
		void setSessionRuntimeMode(activeId, next).then(res => {
			if (seq.current !== mySeq) {
				return; // 更新的切换已接管
			}
			if (res.ok) {
				setUnconfirmed('');
				return;
			}
			setUnconfirmed(res.message || 'unknown');
			toast.error(`审批模式未确认生效：${res.message || 'unknown'}`);
		});
	};

	return (
		<div ref={rootRef} className="relative shrink-0">
			<button
				type="button"
				aria-haspopup="menu"
				aria-expanded={open}
				aria-label={
					unconfirmed ? '审批模式（本会话未确认生效）' : '审批模式'
				}
				title={
					unconfirmed
						? `本会话尚未确认切到「${current.label}」：${unconfirmed}`
						: undefined
				}
				onClick={() => setOpen(v => !v)}
				className={cn(
					'inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-xs text-mute transition-colors',
					'hover:bg-ink/[0.06] hover:text-ink',
					open && 'bg-ink/[0.08] text-ink',
					unconfirmed && 'text-warn',
				)}
			>
				<CurrentIcon className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />
				<span>{current.label}</span>
				{unconfirmed ? (
					<span
						role="img"
						aria-label="未确认生效"
						className="h-1.5 w-1.5 shrink-0 rounded-full bg-warn"
					/>
				) : null}
				<ChevronDown
					className={cn(
						'xy-caret h-3 w-3',
						open && 'is-open',
					)}
				/>
			</button>

			{open ? (
				<div
					role="menu"
					className="xy-menu-flyout absolute bottom-full left-0 z-50 mb-1.5 w-[280px] rounded-xl border border-line/50 p-1.5"
				>
					<div className="px-2 py-1.5">
						<span className="text-xs font-semibold text-ink">
							应如何批准 XEYO 操作？
						</span>
					</div>
					{MODES.map(item => {
						const Icon = item.Icon;
						const selected = item.mode === mode;
						return (
							<button
								key={item.mode}
								type="button"
								role="menuitem"
								onClick={() => selectMode(item.mode)}
								className={cn(
									'flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors',
									selected
										? 'text-accent'
										: 'text-ink-soft hover:bg-paper-deep',
								)}
							>
								<Icon
									className={cn(
										'mt-0.5 h-4 w-4 shrink-0',
										item.danger ? 'text-warn' : 'text-mute',
									)}
									strokeWidth={1.75}
								/>
								<span className="min-w-0 flex-1">
									<span
										className={cn(
											'block text-[13px] font-semibold',
											item.danger && 'text-warn',
										)}
									>
										{item.label}
									</span>
									<span
										className={cn(
											'mt-0.5 block text-[11px] leading-snug',
											item.danger ? 'text-warn/80' : 'text-mute',
										)}
									>
										{item.desc}
									</span>
								</span>
								{selected ? (
									<span className="pt-0.5 text-accent">✓</span>
								) : null}
							</button>
						);
					})}
				</div>
			) : null}
		</div>
	);
}
