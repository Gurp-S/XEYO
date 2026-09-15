import {useState} from 'react';
import {ChevronDown} from 'lucide-react';
import {resolveAsk} from '@/lib/api';
import {toast} from '@/lib/toast';
import {usePendingAskForActiveSession} from '@/hooks/usePendingForActiveSession';
import {useChatStore, type PendingAskInfo} from '@/stores/chatStore';
import type {AskQuestion, AskQuestionOption} from '@/lib/api';
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

/** 每题的作答状态：options 题存选中 label（multiSelect 可多个），无 options 题存自由文本。 */
type QuestionAnswers = Record<number, string[]>;

function buildCombinedAnswer(
	questions: AskQuestion[],
	sel: QuestionAnswers,
	free: Record<number, string>,
): string | null {
	const lines: string[] = [];
	for (let i = 0; i < questions.length; i++) {
		const q = questions[i];
		const picked = sel[i] ?? [];
		const freeText = (free[i] ?? '').trim();
		const answer = q.options.length > 0 ? picked.join('；') : freeText;
		if (!answer) {
			// 有未作答的题：返回 null 由调用方提示，不产出残缺答案。
			return null;
		}
		lines.push(`${i + 1}. ${answer}`);
	}
	return lines.join('\n');
}

function AskCard({pending}: {pending: PendingAskInfo}) {
	// 有选项按钮时不预填自由输入（避免把「继续」塞进输入框）；仅纯自由提问才用 default。
	const [value, setValue] = useState(
		(pending.options?.length ?? 0) > 0 ? '' : (pending.default ?? ''),
	);
	// 分题作答状态（仅多问题表单用）；default 命中选项时预选。
	const questions = pending.questions ?? [];
	const isForm = questions.length > 1;
	const [sel, setSel] = useState<QuestionAnswers>(() => {
		const init: QuestionAnswers = {};
		questions.forEach((q, i) => {
			if (!q.default) return;
			if (q.options.some(o => o.label === q.default)) {
				init[i] = [q.default];
			}
		});
		return init;
	});
	const [free, setFree] = useState<Record<number, string>>({});
	// 提交中：防止双击重复 resolve；失败时保留面板与已选内容供重试。
	const [submitting, setSubmitting] = useState(false);
	const [expanded, setExpanded] = useState(true);
	const options = pending.options ?? [];

	const submit = (answer: string) => {
		const trimmed = answer.trim();
		if (!trimmed || submitting) {
			return;
		}
		void doResolve(trimmed);
	};

	const doResolve = async (answer: string) => {
		setSubmitting(true);
		// 先 resolve 后清面板：失败时保留挂起与已选，引擎不会无人应答地卡死。
		const ok = await resolveAsk(pending.requestId, answer);
		if (ok) {
			useChatStore.getState().setPendingAsk?.(null);
		} else {
			toast.error('提交失败（请求未送达），请重试');
			setSubmitting(false);
		}
	};

	const submitForm = () => {
		if (submitting) return;
		const combined = buildCombinedAnswer(questions, sel, free);
		if (combined === null) {
			toast.error('还有问题未作答');
			return;
		}
		void doResolve(combined);
	};

	const freeText = !isForm && options.length === 0 && questions.length === 0;

	/** 单题（含 legacy 平铺）：保持旧的即点即答交互。 */
	const singleOptions = isForm
		? []
		: (questions[0]?.options.map(o => o.label) ?? options);

	const toggle = (qi: number, label: string, multiSelect: boolean) => {
		setSel(prev => {
			const cur = prev[qi] ?? [];
			if (multiSelect) {
				const next = cur.includes(label)
					? cur.filter(l => l !== label)
					: [...cur, label];
				return {...prev, [qi]: next};
			}
			return {...prev, [qi]: cur.includes(label) ? [] : [label]};
		});
	};

	const countLabel = isForm
		? `${questions.length} 个问题`
		: singleOptions.length
			? `${singleOptions.length} 个选项`
			: '自由作答';

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
				<span className="xy-panel-ask-count">({countLabel})</span>
				<span className="xy-panel-ask-dot" aria-hidden="true" />
			</div>

			<PanelCollapse open={expanded} className="xy-panel-ask-body">
				{isForm ? (
					<form
						onSubmit={e => {
							e.preventDefault();
							submitForm();
						}}
					>
						{questions.map((q, qi) => (
							<QuestionBlock
								key={`${qi}-${q.question.slice(0, 24)}`}
								index={qi}
								q={q}
								picked={sel[qi] ?? []}
								freeValue={free[qi] ?? ''}
								onToggle={label => toggle(qi, label, q.multiSelect)}
								onFreeChange={t => setFree(prev => ({...prev, [qi]: t}))}
							/>
						))}
						<div className="xy-panel-ask-free">
							<button
								type="submit"
								className="xy-panel-ask-submit"
								title="提交全部答案"
								disabled={
									submitting ||
									buildCombinedAnswer(questions, sel, free) === null
								}
							>
								{submitting ? '提交中…' : '提交全部答案'}
							</button>
						</div>
					</form>
				) : (
					<>
						<div className="xy-panel-ask-q">{pending.question}</div>

						{singleOptions.length > 0 ? (
							<div className="xy-panel-ask-opts">
								{singleOptions.map((opt, oi) => (
									<button
										key={`${oi}-${opt}`}
										type="button"
										className="xy-panel-ask-opt"
										disabled={submitting}
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
								disabled={submitting}
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
								disabled={!value.trim() || submitting}
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
					</>
				)}
			</PanelCollapse>
		</div>
	);
}

/** 分题块：题干 + 选项组（单选/多选）或自由输入。 */
function QuestionBlock({
	index,
	q,
	picked,
	freeValue,
	onToggle,
	onFreeChange,
}: {
	index: number;
	q: AskQuestion;
	picked: string[];
	freeValue: string;
	onToggle: (label: string) => void;
	onFreeChange: (text: string) => void;
}) {
	return (
		<div className="xy-panel-ask-qblock">
			<div className="xy-panel-ask-q">
				{index + 1}. {q.question}
				{q.multiSelect ? (
					<span className="xy-panel-ask-multi-hint">（可多选）</span>
				) : null}
			</div>
			{q.options.length > 0 ? (
				<div
					className="xy-panel-ask-opts"
					role={q.multiSelect ? 'group' : 'radiogroup'}
				>
					{q.options.map((opt: AskQuestionOption, oi) => {
						const active = picked.includes(opt.label);
						return (
							<button
								key={`${oi}-${opt.label}`}
								type="button"
								className={cn('xy-panel-ask-opt', active && 'is-picked')}
								aria-pressed={q.multiSelect ? active : undefined}
								aria-checked={q.multiSelect ? undefined : active}
								title={opt.description}
								onClick={() => onToggle(opt.label)}
							>
								{opt.label}
								{opt.description ? (
									<span className="xy-panel-ask-opt-desc">
										{opt.description}
									</span>
								) : null}
							</button>
						);
					})}
				</div>
			) : (
				<input
					className="xy-panel-ask-input"
					placeholder="输入你的回答…"
					value={freeValue}
					onChange={e => onFreeChange(e.target.value)}
				/>
			)}
		</div>
	);
}
