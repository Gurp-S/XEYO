import {useState} from 'react';
import {ChevronDown} from 'lucide-react';
import {resolveAsk} from '@/lib/api';
import {usePendingAskForActiveSession} from '@/hooks/usePendingForActiveSession';
import {useChatStore, type PendingAskInfo} from '@/stores/chatStore';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {cn} from '@/lib/utils';
import {DockPresence} from './DockPresence';
import {PanelCollapse} from './PanelCollapse';

/** 助手向用户提问的贴输入框面板（变体 C：可折叠 Todo 式，底部与发送框一体）。 */
export function AskUserDialog() {
	const pending = usePendingAskForActiveSession();
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));

	return (
		<DockPresence open={Boolean(pending)} smoothness={smoothness}>
			{pending ? (
				<AskCard key={pending.requestId} pending={pending} />
			) : null}
		</DockPresence>
	);
}

function AskCard({pending}: {pending: PendingAskInfo}) {
	// 有选项按钮时不预填自由输入（避免把「继续」塞进输入框）；仅纯自由提问才用 default。
	const [value, setValue] = useState(
		(pending.options?.length ?? 0) > 0 ? '' : (pending.default ?? ''),
	);
	const [expanded, setExpanded] = useState(true);
	const options = pending.options ?? [];

	const submit = (answer: string) => {
		const trimmed = answer.trim();
		if (!trimmed) {
			return;
		}
		useChatStore.getState().setPendingAsk?.(null);
		void resolveAsk(pending.requestId, trimmed);
	};

	const freeText = options.length === 0;

	return (
		<div
			className={cn('xy-panel-ask', expanded && 'is-expanded')}
			role="alertdialog"
			aria-label="助手提问"
		>
			<div
				className="xy-panel-ask-head"
				aria-expanded={expanded}
				onClick={() => setExpanded(v => !v)}
			>
				<span className="xy-panel-ask-caret" aria-hidden="true">
					<ChevronDown
						className={cn(
							'size-3.5 transition-transform duration-200 ease-out',
							!expanded && '-rotate-90',
						)}
					/>
				</span>
				<span className="xy-panel-ask-title">Ask the user</span>
				<span className="xy-panel-ask-count">
					({options.length ? options.length : 1} 个选项)
				</span>
				<span className="xy-panel-ask-dot" aria-hidden="true" />
			</div>

			<PanelCollapse open={expanded} className="xy-panel-ask-body">
				<div className="xy-panel-ask-q">{pending.question}</div>

				{options.length > 0 ? (
					<div className="xy-panel-ask-opts">
						{options.map(opt => (
							<button
								key={opt}
								type="button"
								className="xy-panel-ask-opt"
								onClick={() => submit(opt)}
							>
								{opt}
							</button>
						))}
					</div>
				) : null}

				<div className="xy-panel-ask-free">
					<input
						autoFocus={freeText}
						className="xy-panel-ask-input"
						placeholder={freeText ? '输入你的回答…' : '或自由输入…'}
						value={value}
						onChange={e => setValue(e.target.value)}
						onKeyDown={e => {
							if (e.key === 'Enter') {
								submit(value);
							}
						}}
					/>
					<button
						type="button"
						className="xy-panel-ask-send"
						title="提交"
						disabled={!value.trim()}
						onClick={() => submit(value)}
					>
						<svg
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							strokeWidth="2.2"
							aria-hidden
						>
							<path d="M12 19V5M6 11l6-6 6 6" />
						</svg>
					</button>
				</div>
			</PanelCollapse>
		</div>
	);
}
