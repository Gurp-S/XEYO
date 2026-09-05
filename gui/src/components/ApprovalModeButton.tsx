import {ChevronDown, ShieldAlert, ShieldCheck, ShieldQuestion} from 'lucide-react';
import {useState} from 'react';

import {setSessionRuntimeMode} from '@/lib/api/runtimeMode';
import {patchComposerDraftModes} from '@/lib/composerDrafts';
import {cn} from '@/lib/utils';
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
	const current = MODES.find(m => m.mode === mode) ?? MODES[1];
	const CurrentIcon = current.Icon;

	const selectMode = (next: PermissionMode) => {
		update({permissionMode: next});
		if (activeId) {
			patchComposerDraftModes(activeId, {permissionMode: next});
			// 立即写活状态：同一轮内尚未执行的下一工具调用即按新模式判定。
			setSessionRuntimeMode(activeId, next);
		}
		setOpen(false);
	};

	return (
		<div className="relative shrink-0">
			<button
				type="button"
				aria-haspopup="menu"
				aria-expanded={open}
				aria-label="审批模式"
				onClick={() => setOpen(v => !v)}
				className={cn(
					'inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-xs text-mute transition-colors',
					'hover:bg-ink/[0.06] hover:text-ink',
					open && 'bg-ink/[0.08] text-ink',
				)}
			>
				<CurrentIcon className="h-3.5 w-3.5" strokeWidth={1.75} />
				<span>{current.label}</span>
				<ChevronDown
					className={cn(
						'h-3 w-3 opacity-50 transition-transform',
						open && 'rotate-180 opacity-70',
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
