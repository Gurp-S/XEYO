import {useState} from 'react';
import {ChevronDown, ChevronLeft, ChevronRight} from 'lucide-react';
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

/** 拆掉约定俗成的推荐后缀（dsh 同款），选中值不带后缀。 */
export function parseRecommendedLabel(label: string): {
	label: string;
	recommended: boolean;
} {
	const suffix = /\s*(?:\((?:recommended|推荐)\)|（(?:recommended|推荐)）)\s*$/i;
	return suffix.test(label)
		? {label: label.replace(suffix, ''), recommended: true}
		: {label, recommended: false};
}

/** 每题的草稿作答（dsh 同款三元组）：选中 labels + 自由文本 + 跳过标记。 */
type QuestionDraft = {selected: string[]; custom: string; skipped: boolean};

const emptyDraft = (): QuestionDraft => ({selected: [], custom: '', skipped: false});

/** 结构化多题的答案 JSON（模型侧按 id 对号；跳过题 selected 为空数组）。 */
function buildAnswersJson(questions: AskQuestion[], drafts: QuestionDraft[]): string {
	const answers = questions.map((q, i) => {
		const d = drafts[i] ?? emptyDraft();
		if (d.skipped) {
			return {id: q.id, selected: []};
		}
		const custom = d.custom.trim();
		// dsh 口径：单选题填了自由文本则以文本作答；多选题文本与勾选并存。
		const selected =
			custom === '' || q.multiSelect ? d.selected : [];
		return custom === ''
			? {id: q.id, selected}
			: {id: q.id, selected, custom};
	});
	return JSON.stringify({answers});
}

/** dsh 同款单题向导流：一次一题 + 翻页 + 跳过 + 校验后整组提交。 */
function QuestionFlow({
	questions,
	submitting,
	onSubmit,
}: {
	questions: AskQuestion[];
	submitting: boolean;
	onSubmit: (answer: string) => void;
}) {
	const [index, setIndex] = useState(0);
	const [drafts, setDrafts] = useState<QuestionDraft[]>(() =>
		questions.map(q => {
			const base = emptyDraft();
			// default 命中选项时预选（多选同值也只预选一个，够用且不出错）。
			if (q.default && q.options.some(o => o.label === q.default)) {
				return {...base, selected: [q.default]};
			}
			return base;
		}),
	);
	const [error, setError] = useState<string | null>(null);

	const q = questions[index] ?? questions[0];
	const draft = drafts[index] ?? emptyDraft();
	const answered = (d: QuestionDraft) =>
		d.selected.length > 0 || d.custom.trim() !== '';
	const completed = (d: QuestionDraft) => answered(d) || d.skipped;

	const write = (nextIndex: number, nextDrafts: QuestionDraft[]) => {
		setIndex(nextIndex);
		setDrafts(nextDrafts);
		setError(null);
	};

	const patch = (update: (d: QuestionDraft) => QuestionDraft) => {
		setDrafts(prev => prev.map((d, i) => (i === index ? update(d) : d)));
		setError(null);
	};

	const choose = (label: string) => {
		if (q.multiSelect) {
			patch(d => ({
				...d,
				selected: d.selected.includes(label)
					? d.selected.filter(l => l !== label)
					: [...d.selected, label],
				skipped: false,
			}));
			return;
		}
		// 单选：点击即落定，非末题自动跳下一题（dsh 同款节奏）。
		const next = drafts.map((d, i) =>
			i === index ? {selected: [label], custom: '', skipped: false} : d,
		);
		write(index < questions.length - 1 ? index + 1 : index, next);
	};

	const setCustom = (text: string) => {
		patch(d => ({
			...d,
			// 单选：自由输入取代勾选；多选：文本与勾选并存。
			selected: q.multiSelect ? d.selected : [],
			custom: text,
			skipped: false,
		}));
	};

	const go = (nextIndex: number) => {
		if (nextIndex < 0 || nextIndex >= questions.length) return;
		write(nextIndex, drafts);
	};

	const skip = () => {
		const next = drafts.map((d, i) =>
			i === index ? {selected: [], custom: '', skipped: true} : d,
		);
		if (index < questions.length - 1) {
			write(index + 1, next);
			return;
		}
		submitAll(next);
	};

	const submitAll = (values: QuestionDraft[]) => {
		const missing = values.findIndex(d => !completed(d));
		if (missing >= 0) {
			setIndex(missing);
			setDrafts(values);
			setError('还有问题未作答');
			return;
		}
		onSubmit(buildAnswersJson(questions, values));
	};

	const continueFlow = () => {
		if (!answered(draft)) {
			setError('请先作答（选择或输入）');
			return;
		}
		if (index < questions.length - 1) {
			write(index + 1, drafts);
			return;
		}
		submitAll(drafts);
	};

	const hasOptions = q.options.length > 0;

	return (
		<div>
			{q.header ? <div className="xy-panel-ask-eyebrow">{q.header}</div> : null}
			<div className="xy-panel-ask-q">
				{index + 1}. {q.question}
				{q.multiSelect ? (
					<span className="xy-panel-ask-multi-hint">（可多选）</span>
				) : null}
			</div>
			{q.detail ? <div className="xy-panel-ask-detail">{q.detail}</div> : null}

			{hasOptions ? (
				<div
					className="xy-panel-ask-opts"
					role={q.multiSelect ? 'group' : 'radiogroup'}
				>
					{q.options.map((opt: AskQuestionOption, oi) => {
						const picked = draft.selected.includes(opt.label);
						const display = parseRecommendedLabel(opt.label);
						return (
							<button
								key={`${oi}-${opt.label}`}
								type="button"
								className={cn('xy-panel-ask-opt', picked && 'is-picked')}
								role={q.multiSelect ? 'checkbox' : 'radio'}
								aria-checked={picked}
								disabled={submitting}
								onClick={() => choose(opt.label)}
							>
								<span className="xy-panel-ask-opt-main">
									{q.multiSelect ? (
										<span
											className={cn(
												'xy-ask-check',
												picked && 'is-on',
											)}
											aria-hidden
										>
											<svg
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												strokeWidth="3"
											>
												<path d="M5 13l4 4 10-10" />
											</svg>
										</span>
									) : (
										<span className="xy-ask-num" aria-hidden>
											{oi + 1}
										</span>
									)}
									<span className="xy-panel-ask-opt-label">
										{display.label}
										{display.recommended ? (
											<span className="xy-ask-badge">推荐</span>
										) : null}
									</span>
								</span>
								{opt.description ? (
									<span className="xy-panel-ask-opt-desc">
										{opt.description}
									</span>
								) : null}
							</button>
						);
					})}

					{/* 自由输入行（dsh 同款"Other"）：单选填文本即取代勾选 */}
					<div
						className={cn(
							'xy-ask-custom',
							draft.custom !== '' && 'is-active',
						)}
					>
						{q.multiSelect ? (
							<span
								className={cn(
									'xy-ask-check',
									draft.custom !== '' && 'is-on',
								)}
								aria-hidden
							>
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									strokeWidth="3"
								>
									<path d="M5 13l4 4 10-10" />
								</svg>
							</span>
						) : (
							<span className="xy-ask-num" aria-hidden>
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									strokeWidth="2"
								>
									<path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
								</svg>
							</span>
						)}
						<input
							className="xy-ask-custom-input"
							placeholder="或自由输入…"
							value={draft.custom}
							disabled={submitting}
							onChange={e => setCustom(e.target.value)}
							onKeyDown={e => {
								if (e.key === 'Enter') {
									e.preventDefault();
									continueFlow();
								}
							}}
						/>
					</div>
				</div>
			) : (
				<input
					autoFocus
					className="xy-panel-ask-input"
					placeholder="输入你的回答…"
					value={draft.custom}
					disabled={submitting}
					onChange={e => setCustom(e.target.value)}
					onKeyDown={e => {
						if (e.key === 'Enter') {
							e.preventDefault();
							continueFlow();
						}
					}}
				/>
			)}

			<div className="xy-panel-ask-foot">
				<div className="xy-ask-pager">
					<button
						type="button"
						className="xy-ask-icon-btn"
						aria-label="上一题"
						disabled={index === 0 || submitting}
						onClick={() => go(index - 1)}
					>
						<ChevronLeft className="size-3.5" />
					</button>
					<span className="xy-ask-progress">
						{index + 1} / {questions.length}
					</span>
					<button
						type="button"
						className="xy-ask-icon-btn"
						aria-label="下一题"
						disabled={index === questions.length - 1 || submitting}
						onClick={() => go(index + 1)}
					>
						<ChevronRight className="size-3.5" />
					</button>
				</div>
				<span className="xy-ask-feedback" role="status">
					{error}
				</span>
				<div className="xy-ask-foot-actions">
					<button
						type="button"
						className="xy-ask-skip"
						disabled={submitting}
						onClick={skip}
					>
						跳过
					</button>
					<button
						type="button"
						className="xy-panel-ask-submit xy-ask-next"
						disabled={submitting || !answered(draft)}
						onClick={continueFlow}
					>
						{submitting
							? '提交中…'
							: index === questions.length - 1
								? '提交全部答案'
								: '下一题'}
					</button>
				</div>
			</div>
		</div>
	);
}

function AskCard({pending}: {pending: PendingAskInfo}) {
	// 有选项按钮时不预填自由输入（避免把「继续」塞进输入框）；仅纯自由提问才用 default。
	const [value, setValue] = useState(
		(pending.options?.length ?? 0) > 0 ? '' : (pending.default ?? ''),
	);
	// 提交中：防止双击重复 resolve；失败时保留面板与已选内容供重试。
	const [submitting, setSubmitting] = useState(false);
	const [expanded, setExpanded] = useState(true);
	const options = pending.options ?? [];

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

	const submit = (answer: string) => {
		const trimmed = answer.trim();
		if (!trimmed || submitting) {
			return;
		}
		void doResolve(trimmed);
	};

	const questions = pending.questions ?? [];
	const isWizard = questions.length > 0;
	const freeText = !isWizard && options.length === 0;
	const countLabel = isWizard
		? `${questions.length} 个问题`
		: options.length
			? `${options.length} 个选项`
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
				{isWizard ? (
					<QuestionFlow
						questions={questions}
						submitting={submitting}
						onSubmit={a => void doResolve(a)}
					/>
				) : (
					<>
						<div className="xy-panel-ask-q">{pending.question}</div>

						{options.length > 0 ? (
							<div className="xy-panel-ask-opts">
								{options.map((opt, oi) => (
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
