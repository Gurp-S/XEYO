import {Eye, EyeOff, ImagePlus, Pencil, Plus, Trash2, X} from 'lucide-react';
import {useEffect, useRef, useState} from 'react';
import {usePresence} from '@/hooks/usePresence';
import {AccentColorPicker} from '@/components/AccentColorPicker';
import {GrantsPanel} from '@/components/GrantsPanel';
import {ReasoningLevelsSelect} from '@/components/ReasoningLevelsSelect';
import {RuntimePresetSetting} from '@/components/RuntimePresetSetting';
import {BG_PICK_MAX_BYTES, compressBackgroundImage} from '@/lib/bgImage';
import {setRewindGcSettings} from '@/lib/api';
import {cn} from '@/lib/utils';
import {toast} from '@/lib/toast';
import {confirmDialog} from '@/lib/inlineDialog';
import {useRemoteStore} from '@/stores/remoteStore';
import {allowsEmptyApiKey} from '@/lib/localTestGate';
import {invokePet} from '@/pet/PetBridge';
import {
	accentForThemeId,
	ACCENT_RECOMMENDATIONS,
	PROVIDER_LABEL,
	REASONING_EFFORTS,
	keyFingerprint,
	profileModelIds,
	useSettingsStore,
	type ModelInput,
	type ModelProfile,
	type ProviderId,
	type RemoteChannel,
} from '@/stores/settingsStore';
import {getThemeMeta, type ThemeId} from '@/theme/catalog';
import {ThemePicker} from '@/theme/ThemePicker';
import {BashRoutingSetting} from './BashRoutingSetting';
import {MemorySwitchesSetting} from './MemorySwitchesSetting';
import {PaneLayoutSetting} from './PaneLayoutSetting';

type Props = {
	open: boolean;
	onClose: () => void;
};

/** 账号表单里单个「模型行」的草稿（数字字段以字符串编辑，保存时再转 number）。 */
type DraftModelRow = {
	id: string;
	contextLimit: string;
	maxOutputTokens: string;
	inputType: NonNullable<ModelInput['inputType']>;
	outputType: NonNullable<ModelInput['outputType']>;
	/** 该模型支持的思考等级（多选，可空）。 */
	reasoningLevels: ModelInput['reasoningLevels'];
	/** 该模型的默认思考等级；空 = 用会话级。 */
	defaultReasoningEffort: ModelInput['defaultReasoningEffort'];
};

const emptyDraftModel = (): DraftModelRow => ({
	id: '',
	contextLimit: '',
	maxOutputTokens: '',
	inputType: 'text',
	outputType: 'text',
	reasoningLevels: [],
	defaultReasoningEffort: '',
});

/** 把已保存的 ModelInput 转成表单草稿行。 */
const modelToDraftRow = (m: ModelInput): DraftModelRow => ({
	id: m.id,
	contextLimit: m.contextLimit != null ? String(m.contextLimit) : '',
	maxOutputTokens: m.maxOutputTokens != null ? String(m.maxOutputTokens) : '',
	inputType: m.inputType ?? 'text',
	outputType: m.outputType ?? 'text',
	reasoningLevels: m.reasoningLevels ?? [],
	defaultReasoningEffort: m.defaultReasoningEffort ?? '',
});

/** 把表单草稿行转成 ModelInput（丢弃 id 为空的行；可选字段留空不发送）。 */
const draftRowsToModels = (rows: DraftModelRow[]): ModelInput[] =>
	rows
		.map(r => {
			const id = r.id.trim();
			if (!id) {
				return null;
			}
			const contextLimit = Math.floor(Number(r.contextLimit) || 0);
			const maxOutputTokens = Math.floor(Number(r.maxOutputTokens) || 0);
			const out: ModelInput = {
				id,
				inputType: r.inputType,
				outputType: r.outputType,
			};
			if (contextLimit > 0) {
				out.contextLimit = contextLimit;
			}
			if (maxOutputTokens > 0) {
				out.maxOutputTokens = maxOutputTokens;
			}
			if (r.reasoningLevels && r.reasoningLevels.length > 0) {
				out.reasoningLevels = r.reasoningLevels;
			}
			if (r.defaultReasoningEffort) {
				out.defaultReasoningEffort = r.defaultReasoningEffort;
			}
			return out;
		})
		.filter((m): m is ModelInput => m !== null);

export function SettingsModal({open, onClose}: Props) {
	const provider = useSettingsStore(s => s.provider);
	const profiles = useSettingsStore(s => s.profiles) ?? [];
	const activeProfileId = useSettingsStore(s => s.activeProfileId);
	const addProfile = useSettingsStore(s => s.addProfile);
	const selectProfile = useSettingsStore(s => s.selectProfile);
	const removeProfile = useSettingsStore(s => s.removeProfile);
	const bgImage = useSettingsStore(s => s.bgImage);
	const bgOpacity = useSettingsStore(s => s.bgOpacity);
	const bgBlur = useSettingsStore(s => s.bgBlur);
	const theme = useSettingsStore(s => s.theme);
	const accentByTheme = useSettingsStore(s => s.accentByTheme ?? {});
	const accentHistory = useSettingsStore(s => s.accentHistory ?? []);
	const accentForTheme = accentForThemeId(accentByTheme, theme);
	const themeDefaultAccent = getThemeMeta(theme).defaultAccent;
	const settingsInitialTab = useSettingsStore(s => s.settingsInitialTab);

	const setThemeAccent = (hex: string) => {
		const next: Partial<Record<ThemeId, string>> = {...accentByTheme};
		const c = hex.trim();
		if (c) {
			next[theme] = c;
		} else {
			delete next[theme];
		}
		update({accentByTheme: next});
	};
	const smoothness = useSettingsStore(s => s.smoothness !== false);
	const rewindFullTreeRestore = useSettingsStore(
		s => s.rewindFullTreeRestore === true,
	);
	const rewindGcKeepRecent = useSettingsStore(s => s.rewindGcKeepRecent);
	const rewindGcMaxBytes = useSettingsStore(s => s.rewindGcMaxBytes);
	const titleBarDivider = useSettingsStore(s => s.titleBarDivider !== false);
	const paneEaseSilky = useSettingsStore(s => s.paneEaseSilky === true);
	const stickyBubbles = useSettingsStore(s => s.stickyBubbles === true);
			
		const pastureReducedMotion = useSettingsStore(s => s.pastureReducedMotion === true);
			const pasturePaused = useSettingsStore(s => s.pasturePaused === true);
			const xeyoPetEnabled = useSettingsStore(s => s.xeyoPetEnabled !== false);
			const xeyoPetReducedMotion = useSettingsStore(s => s.xeyoPetReducedMotion === true);
			const xeyoPetId = useSettingsStore(s => s.xeyoPetId);
			const remoteChannel = useSettingsStore(s => s.remoteChannel);
	const maxBudgetUsd = useSettingsStore(s => s.maxBudgetUsd);
	const searxngUrl = useSettingsStore(s => s.searxngUrl ?? '');
	const outputCompact = useSettingsStore(s => s.outputCompact === true);
	const outputMode = useSettingsStore(s => s.outputMode ?? 'lite');
	const codeCompact = useSettingsStore(s => s.codeCompact === true);
	const codeMode = useSettingsStore(s => s.codeMode ?? 'lite');
	const reasoningTail = useSettingsStore(s => s.reasoningTail === true);
	const showExperimental = useSettingsStore(s => s.showExperimental === true);
	const update = useSettingsStore(s => s.update);
	const updateProfile = useSettingsStore(s => s.updateProfile);
	const [gcKeepRecentDraft, setGcKeepRecentDraft] = useState<string>(
		() => (rewindGcKeepRecent == null ? '' : String(rewindGcKeepRecent)),
	);
	const [gcMaxBytesDraft, setGcMaxBytesDraft] = useState<string>(
		() => (rewindGcMaxBytes == null ? '' : String(rewindGcMaxBytes)),
	);
	useEffect(() => {
		if (open) {
			setGcKeepRecentDraft(rewindGcKeepRecent == null ? '' : String(rewindGcKeepRecent));
			setGcMaxBytesDraft(rewindGcMaxBytes == null ? '' : String(rewindGcMaxBytes));
		}
	}, [open, rewindGcKeepRecent, rewindGcMaxBytes]);
	// Escape 关闭模态（2026-09-05 交互审计：此前无键盘退出路径，
	// 遮罩下的后续交互全部被卡住；命令面板/其他浮层均有 Esc 退出惯例）。
	useEffect(() => {
		if (!open) {
			return;
		}
		const onKeyDown = (e: KeyboardEvent) => {
			if (e.isComposing) {
				return;
			}
			if (e.key === 'Escape' && !e.defaultPrevented) {
				e.stopPropagation();
				onClose();
			}
		};
		window.addEventListener('keydown', onKeyDown, true);
		return () => window.removeEventListener('keydown', onKeyDown, true);
	}, [open, onClose]);
	const applyGcSettings = async () => {
		const keepRaw = Number(gcKeepRecentDraft);
		const keepInt =
			gcKeepRecentDraft.trim() === ''
				? null
				: Number.isFinite(keepRaw)
					? Math.max(1, Math.trunc(keepRaw))
					: null;
		const bytesRaw = Number(gcMaxBytesDraft);
		const bytesInt =
			gcMaxBytesDraft.trim() === ''
				? null
				: Number.isFinite(bytesRaw)
					? Math.max(0, Math.trunc(bytesRaw))
					: null;
		const ok = await setRewindGcSettings(keepInt, bytesInt);
		if (ok) {
			update({rewindGcKeepRecent: keepInt, rewindGcMaxBytes: bytesInt});
			toast.success('已保存回溯清理设置');
		} else {
			toast.error('保存失败，请检查后端可达');
		}
	};
	const fileRef = useRef<HTMLInputElement>(null);
		const [compressing, setCompressing] = useState(false);
		const {mounted, shown} = usePresence(open, 160);

	const [activeTab, setActiveTab] = useState<
		'appearance' | 'accounts' | 'rewind' | 'perms' | 'pet' | 'remote'
	>('appearance');
		const [showAdd, setShowAdd] = useState(false);
		/** 正在被编辑的账号 id；非空时表单处于「编辑账号」态并预填现存值。 */
		const [editingId, setEditingId] = useState<string | null>(null);
		/** 当前展开显示完整 Key 的账号行 id（同一时刻至多一个，利于扫码/复制）。 */
		const [revealedId, setRevealedId] = useState<string | null>(null);
		/** 表单内 API Key 输入框的明密文切换。 */
		const [showKey, setShowKey] = useState(false);
		const [draft, setDraft] = useState({
			provider: provider as ProviderId,
			name: '',
			note: '',
			website: '',
			apiKey: '',
			baseUrl: '',
			models: [] as DraftModelRow[],
		});
		const [fieldErrors, setFieldErrors] = useState<{
			apiKey?: string;
			baseUrl?: string;
			models?: string;
		}>({});

	useEffect(() => {
		if (open) {
			setActiveTab(settingsInitialTab);
		}
	}, [open, settingsInitialTab]);

		const setXeyoPetEnabled = (next: boolean) => {
			update({xeyoPetEnabled: next});
			const command = next
				? invokePet('character_lift', {x: 220, y: 200})
				: invokePet('character_drop_on_island');
			void command.catch(() => undefined);
		};

		const updateDraftModel = (idx: number, patch: Partial<DraftModelRow>) => {
			setDraft(d => ({
				...d,
				models: d.models.map((m, i) => (i === idx ? {...m, ...patch} : m)),
			}));
			if (fieldErrors.models) {
				setFieldErrors(f => ({...f, models: undefined}));
			}
		};

		const removeDraftModel = (idx: number) => {
			setDraft(d => ({...d, models: d.models.filter((_, i) => i !== idx)}));
		};

		const openAddAccount = () => {
			setEditingId(null);
			setShowKey(false);
			setFieldErrors({});
			setDraft({
				provider,
				name: '',
				note: '',
				website: '',
				apiKey: '',
				baseUrl: '',
				models: [emptyDraftModel()],
			});
			setShowAdd(true);
		};

		const openEditAccount = (p: ModelProfile) => {
			setEditingId(p.id);
			setShowKey(false);
			setFieldErrors({});
			setDraft({
				provider: p.provider,
				name: p.name ?? '',
				note: p.note ?? '',
				website: p.website ?? '',
				apiKey: p.apiKey,
				baseUrl: p.baseUrl,
				// 兼容旧单模型：无 models 数组时从 model/contextLimit/maxOutputTokens 迁移出首行。
				models: (p.models?.length
					? p.models.map(modelToDraftRow)
					: [
							{
								id: p.model,
								contextLimit:
									p.contextLimit != null ? String(p.contextLimit) : '',
								maxOutputTokens:
									p.maxOutputTokens != null
										? String(p.maxOutputTokens)
										: '',
								inputType: 'text' as const,
								outputType: 'text' as const,
								reasoningLevels: [],
								defaultReasoningEffort: '',
							},
						]),
			});
			setShowAdd(true);
		};

		const saveDraftAccount = () => {
			const errs: {apiKey?: string; baseUrl?: string; models?: string} = {};
			if (!draft.apiKey.trim()) {
				errs.apiKey = '请填写 API Key';
			}
			if (!draft.baseUrl.trim()) {
				errs.baseUrl = '请填写 API 请求地址';
			}
			// 模型列表必填；每个模型行 id 与上下文窗口必填（用户填写为准，不再用厂商 /models 覆盖）。
			let hasRowError = false;
			for (const row of draft.models) {
				if (!row.id.trim()) {
					hasRowError = true;
				}
				if (!(Math.floor(Number(row.contextLimit) || 0) > 0)) {
					hasRowError = true;
				}
			}
			if (draft.models.length === 0) {
				errs.models = '请至少添加一个模型';
			} else if (hasRowError) {
				errs.models = '请填写每个模型的 ID 与上下文窗口（token 数）';
			}
			if (errs.apiKey || errs.baseUrl || errs.models) {
				setFieldErrors(errs);
				return;
			}
			const rows = draftRowsToModels(draft.models);
			// 激活模型：优先保留编辑前仍在集合中的那个，否则落到第一个。
			const existing = editingId
				? profiles.find(p => p.id === editingId)
				: undefined;
			const nextModel =
				existing?.model && rows.some(m => m.id === existing.model)
					? existing.model
					: rows[0].id;
			if (editingId) {
				updateProfile(editingId, {
					provider: draft.provider,
					model: nextModel,
					apiKey: draft.apiKey,
					baseUrl: draft.baseUrl,
					name: draft.name,
					note: draft.note,
					website: draft.website,
					models: rows,
				});
				toast.success('已更新账号');
			} else {
				addProfile({
					provider: draft.provider,
					model: nextModel,
					apiKey: draft.apiKey,
					baseUrl: draft.baseUrl,
					name: draft.name,
					note: draft.note,
					website: draft.website,
					models: rows,
				});
				const fp = keyFingerprint(draft.apiKey);
				toast.success(fp ? `已保存账号 ${fp}` : '已保存账号');
			}
			setEditingId(null);
			setShowAdd(false);
			setFieldErrors({});
		};

	if (!mounted) {
		return null;
	}

	const onPickBg = (file: File | undefined) => {
		if (!file || !file.type.startsWith('image/')) {
			return;
		}
		if (file.size > BG_PICK_MAX_BYTES) {
			toast.warn('原图请小于 10MB（保存前会自动压缩）');
			return;
		}
		setCompressing(true);
		void compressBackgroundImage(file)
			.then(dataUrl => {
				update({bgImage: dataUrl});
			})
			.catch(err => {
				toast.error(err instanceof Error ? err.message : String(err));
			})
			.finally(() => setCompressing(false));
	};

	return (
		<div
			className={cn(
				'xy-modal-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4 backdrop-blur-[3px]',
				shown ? 'opacity-100' : 'opacity-0',
			)}
			onClick={onClose}
		>
			<div
				role="dialog"
				aria-modal="true"
				className={cn(
					'xy-modal-panel xy-modal-elevated flex h-[560px] w-[720px] max-w-[92vw] flex-col overflow-hidden rounded-2xl border border-line/80 bg-paper p-5',
					shown ? 'translate-y-0 scale-100 opacity-100' : 'translate-y-2 scale-[0.98] opacity-0',
				)}
				onClick={e => e.stopPropagation()}
			>
				<div className="mb-4 flex items-center justify-between">
					<h2 className="font-sans text-base font-semibold text-ink">
						设置
					</h2>
					<button
						type="button"
						onClick={onClose}
						className="xy-icon-btn rounded-xl p-1.5 text-mute hover:bg-paper-deep"
					>
						<X className="h-4 w-4" />
					</button>
				</div>
				<div className="grid min-h-0 flex-1 grid-cols-[150px_1fr] gap-4">
					<nav className="space-y-1">
						{([
							['appearance', '外观'],
							['accounts', '模型与账号'],
							['perms', '权限'],
							['rewind', '回溯'],
							['pet', '桌宠'],
							['remote', '远程 · 微信'],
						] as const).map(([id, label]) => (
							<button
								key={id}
								type="button"
								onClick={() => setActiveTab(id)}
								className={cn(
									'block w-full rounded-lg px-3 py-2 text-left text-[13px] transition-colors',
									activeTab === id
										? 'bg-accent-soft text-accent'
										: 'text-ink-soft hover:bg-paper-deep hover:text-ink',
								)}
							>
								{label}
							</button>
						))}
					</nav>
					<div className="min-w-0 flex-1 overflow-y-auto pr-1">

				<section className={cn('mb-5 space-y-3', activeTab !== 'appearance' && 'hidden')}>
					<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
						外观
					</h3>
					<ThemePicker
						value={theme}
						onChange={id => update({theme: id})}
					/>

					<PaneLayoutSetting />

					{/* T32：半成品实验功能收进「实验菜单」——默认隐藏，需显式开启 */}
					<div className="rounded-xl border border-line/70 bg-glass-strong">
						<button
							type="button"
							role="switch"
							aria-checked={showExperimental}
							onClick={() => update({showExperimental: !showExperimental})}
							className={cn(
								'xy-press flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors',
								showExperimental ? 'bg-accent-soft/70' : 'bg-glass-strong hover:bg-paper-deep',
							)}
						>
							<span>
								<span className="block text-sm text-ink">实验功能</span>
								<span className="mt-0.5 block text-[11px] leading-snug text-mute">
									{showExperimental
										? '已显示半成品实验入口（AgentMap 代码/架构地图等）'
										: '隐藏 AgentMap 等实验功能（默认）'}
								</span>
							</span>
							<span
								className={cn(
									'relative h-5 w-9 shrink-0 rounded-full transition-colors',
									showExperimental ? 'bg-accent' : 'bg-line',
								)}
								aria-hidden
							>
								<span
									className={cn(
										'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
										showExperimental ? 'translate-x-4' : 'translate-x-0',
									)}
								/>
							</span>
						</button>
					</div>

					{/* 强调色：仅作用于当前主题 */}
					<div className="space-y-2.5 rounded-xl border border-line/70 bg-glass-strong p-3">
						<div className="flex items-center justify-between">
							<span className="text-sm text-ink">强调色</span>
							{accentForTheme ? (
								<button
									type="button"
									onClick={() => setThemeAccent('')}
									className="text-[11px] text-mute hover:text-accent"
								>
									恢复默认
								</button>
							) : (
								<span className="text-[11px] text-mute">当前使用主题默认</span>
							)}
						</div>
						<AccentColorPicker
							value={accentForTheme}
							fallback={themeDefaultAccent}
							onChange={hex => setThemeAccent(hex)}
						/>
						<div>
							<div className="flex flex-wrap gap-1.5">
								{ACCENT_RECOMMENDATIONS.map(rec => (
									<button
										key={rec.color}
										type="button"
										title={rec.name}
										aria-label={`强调色 ${rec.name}`}
										onClick={() => setThemeAccent(rec.color)}
										className={cn(
											'h-6 w-6 rounded-full border transition-transform hover:scale-110',
											accentForTheme.toLowerCase() === rec.color
												? 'border-ink ring-2 ring-accent/50'
												: 'border-line',
										)}
										style={{background: rec.color}}
									/>
								))}
							</div>
						</div>
						{accentHistory.length ? (
							<div>
								<div className="flex flex-wrap gap-1.5">
									{accentHistory.map(c => (
										<button
											key={c}
											type="button"
											title={c}
											aria-label={`强调色 ${c}`}
											onClick={() => setThemeAccent(c)}
											className={cn(
												'h-6 w-6 rounded-full border transition-transform hover:scale-110',
												accentForTheme.toLowerCase() === c
													? 'border-ink ring-2 ring-accent/50'
													: 'border-line',
											)}
											style={{background: c}}
										/>
									))}
								</div>
							</div>
						) : null}
					</div>

					<button
						type="button"
						role="switch"
						aria-checked={smoothness}
						onClick={() => update({smoothness: !smoothness})}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
							smoothness
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">流畅</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								输入和滚动跟屏幕刷新；Agent 更新每帧最多提交一次。
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								smoothness ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									smoothness ? 'translate-x-4' : 'translate-x-0',
								)}
							/>
						</span>
						</button>

						<button
							type="button"
							role="switch"
							aria-checked={titleBarDivider}
							onClick={() => update({titleBarDivider: !titleBarDivider})}
							className={cn(
								'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
								titleBarDivider
									? 'border-accent/50 bg-accent-soft'
									: 'border-line bg-glass-strong hover:border-line',
							)}
						>
							<span>
								<span className="block text-sm text-ink">标题栏分割线</span>
								<span className="mt-0.5 block text-[11px] leading-snug text-mute">
									在窗口标题栏底部显示一条细线，与下方内容区分。
								</span>
							</span>
							<span
								className={cn(
									'relative h-5 w-9 shrink-0 rounded-full transition-colors',
									titleBarDivider ? 'bg-accent' : 'bg-line',
								)}
								aria-hidden
							>
								<span
									className={cn(
										'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
										titleBarDivider ? 'translate-x-4' : 'translate-x-0',
									)}
								/>
							</span>
						</button>

						<button
							type="button"
							role="switch"
							aria-checked={paneEaseSilky}
							onClick={() => update({paneEaseSilky: !paneEaseSilky})}
							className={cn(
								'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
								paneEaseSilky
									? 'border-accent/50 bg-accent-soft'
									: 'border-line bg-glass-strong hover:border-line',
							)}
						>
							<span>
								<span className="block text-sm text-ink">侧栏动画：极平滑减速</span>
								<span className="mt-0.5 block text-[11px] leading-snug text-mute">
									默认柔和减速；开启后侧边栏收放用更柔的减速曲线（均 420ms + 40ms）。
								</span>
							</span>
							<span
								className={cn(
									'relative h-5 w-9 shrink-0 rounded-full transition-colors',
									paneEaseSilky ? 'bg-accent' : 'bg-line',
								)}
								aria-hidden
							>
								<span
									className={cn(
										'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
										paneEaseSilky ? 'translate-x-4' : 'translate-x-0',
									)}
								/>
							</span>
						</button>

						<button
							type="button"
							role="switch"
							aria-checked={stickyBubbles}
							onClick={() => update({stickyBubbles: !stickyBubbles})}
							className={cn(
								'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
								stickyBubbles
									? 'border-accent/50 bg-accent-soft'
									: 'border-line bg-glass-strong hover:border-line',
							)}
						>
							<span>
								<span className="block text-sm text-ink">气泡吸顶</span>
								<span className="mt-0.5 block text-[11px] leading-snug text-mute">
									对话中上一条你的消息吸顶为可编辑气泡。默认关：气泡留在原位。
								</span>
							</span>
							<span
								className={cn(
									'relative h-5 w-9 shrink-0 rounded-full transition-colors',
									stickyBubbles ? 'bg-accent' : 'bg-line',
								)}
								aria-hidden
							>
								<span
									className={cn(
										'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
										stickyBubbles ? 'translate-x-4' : 'translate-x-0',
									)}
								/>
							</span>
						</button>

						<div className="grid grid-cols-2 gap-2">
								<button
									type="button"
									role="switch"
									aria-checked={pastureReducedMotion}
									onClick={() => update({pastureReducedMotion: !pastureReducedMotion})}
									className={cn(
										'xy-press rounded-xl border px-3 py-2 text-left transition-colors',
										pastureReducedMotion ? 'border-accent/50 bg-accent-soft' : 'border-line bg-glass-strong hover:border-line',
									)}
								>
									<span className="block text-[12px] text-ink">减少动态</span>
									<span className="mt-0.5 block text-[10px] leading-snug text-mute">仅保留 opacity 状态切换。</span>
								</button>
								<button
									type="button"
									role="switch"
									aria-checked={pasturePaused}
									onClick={() => update({pasturePaused: !pasturePaused})}
									className={cn(
										'xy-press rounded-xl border px-3 py-2 text-left transition-colors',
										pasturePaused ? 'border-accent/50 bg-accent-soft' : 'border-line bg-glass-strong hover:border-line',
									)}
								>
									<span className="block text-[12px] text-ink">暂停桌宠</span>
									<span className="mt-0.5 block text-[10px] leading-snug text-mute">暂停桌宠状态更新，保留当前画面。</span>
								</button>
							</div>
							</section>

							<section className={cn('mb-5 space-y-3', activeTab !== 'pet' && 'hidden')}>
								<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
									桌宠加载器
								</h3>
								<div className="overflow-hidden rounded-xl border border-line/70 bg-glass-strong">
									<button
										type="button"
										role="switch"
										aria-checked={xeyoPetEnabled}
										onClick={() => setXeyoPetEnabled(!xeyoPetEnabled)}
										className={cn(
											'xy-press flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition-colors',
											xeyoPetEnabled ? 'bg-accent-soft/70' : 'bg-glass-strong hover:bg-paper-deep',
										)}
									>
										<span>
											<span className="block text-sm text-ink">XeyoPet 桌宠</span>
											<span className="mt-0.5 block text-[11px] leading-snug text-mute">
												{xeyoPetEnabled ? `已启用 · ${xeyoPetId}` : '已关闭独立透明桌宠窗口'}
											</span>
										</span>
										<span
											className={cn(
												'relative h-5 w-9 shrink-0 rounded-full transition-colors',
												xeyoPetEnabled ? 'bg-accent' : 'bg-line',
											)}
											aria-hidden
										>
											<span
												className={cn(
													'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
													xeyoPetEnabled ? 'translate-x-4' : 'translate-x-0',
												)}
											/>
										</span>
									</button>
									<button
										type="button"
										role="switch"
										aria-checked={xeyoPetReducedMotion}
										onClick={() => update({xeyoPetReducedMotion: !xeyoPetReducedMotion})}
										className={cn(
											'xy-press flex w-full items-center justify-between gap-3 border-t border-line/60 px-3 py-2.5 text-left transition-colors',
											xeyoPetReducedMotion ? 'bg-accent-soft/70' : 'bg-glass-strong hover:bg-paper-deep',
										)}
									>
										<span>
											<span className="block text-sm text-ink">桌宠减少动态</span>
											<span className="mt-0.5 block text-[11px] leading-snug text-mute">仅保留当前状态首帧，适合低打扰使用。</span>
										</span>
										<span
											className={cn(
												'relative h-5 w-9 shrink-0 rounded-full transition-colors',
												xeyoPetReducedMotion ? 'bg-accent' : 'bg-line',
											)}
											aria-hidden
										>
											<span
												className={cn(
													'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
													xeyoPetReducedMotion ? 'translate-x-4' : 'translate-x-0',
												)}
											/>
										</span>
									</button>
								</div>
								<p className="text-[10px] leading-relaxed text-mute">
									未来宠物只需放入 XeyoPet 目录、提供 manifest/图集/气泡，并登记 catalog，不需要修改 XEYO 核心渲染代码。
								</p>
							</section>

						<section className={cn('mb-5 space-y-3', activeTab !== 'accounts' && 'hidden')}>
						<div className="flex items-center justify-between gap-2">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							模型与密钥
						</h3>
						<button
							type="button"
							onClick={openAddAccount}
							className="xy-press inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] text-accent hover:bg-accent-soft"
						>
							<Plus className="h-3.5 w-3.5" />
							添加账号
						</button>
					</div>
					<p className="text-[11px] leading-relaxed text-mute">
						可保存多套服务商 / Key，全部写在本机。模型列表由你在下方手动登记，对话输入框上拉选择。
					</p>

					{showAdd ? (
						<div className="space-y-2 rounded-xl border border-accent/50 bg-accent-soft/40 p-3">
							<div className="flex items-center justify-between">
								<span className="text-xs font-semibold text-accent">
									{editingId ? '编辑账号' : '新建账号'}
								</span>
								<button
									type="button"
									onClick={() => {
										setShowAdd(false);
										setEditingId(null);
									}}
									className="text-[11px] text-mute hover:text-ink"
								>
									取消
								</button>
							</div>
							<div className="grid grid-cols-2 gap-2">
								<label className="block text-xs">
									<span className="mb-1 block text-mute">供应商名称</span>
									<input
										className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
										placeholder="例如：DeepSeek 官方"
										value={draft.name}
										onChange={e => setDraft(d => ({...d, name: e.target.value}))}
									/>
								</label>
								<label className="block text-xs">
									<span className="mb-1 block text-mute">备注</span>
									<input
										className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
										placeholder="例如：公司专用账号"
										value={draft.note}
										onChange={e => setDraft(d => ({...d, note: e.target.value}))}
									/>
								</label>
							</div>
							<label className="block text-xs">
								<span className="mb-1 block text-mute">官网链接（可选）</span>
								<input
									className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
									placeholder="https://example.com"
									value={draft.website}
									onChange={e => setDraft(d => ({...d, website: e.target.value}))}
								/>
							</label>
							<label className="block text-xs">
								<span className="mb-1 block text-mute">服务商</span>
								<select
									className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
									value={draft.provider}
									onChange={e => setDraft(d => ({...d, provider: e.target.value as ProviderId}))}
								>
<option value="deepseek">DeepSeek</option>
									<option value="openai">OpenAI</option>
									{/* 本地模型仅 localTestGate 开启时可选（T25c）。 */}
									{allowsEmptyApiKey('local') && (
										<option value="local">本地模型（测试）</option>
									)}
								</select>
							</label>
							<div className="text-xs">
								<span className="mb-1 block text-mute">API Key（仅本机）</span>
								<div className="flex items-center gap-2">
									<input
										type={showKey ? 'text' : 'password'}
										className="xy-surface min-w-0 flex-1 rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
										style={
											fieldErrors.apiKey
												? {borderColor: 'var(--xy-danger)'}
												: undefined
										}
										placeholder="只需要填这里"
										value={draft.apiKey}
										onChange={e => {
											setDraft(d => ({...d, apiKey: e.target.value}));
											if (fieldErrors.apiKey) {
												setFieldErrors(f => ({...f, apiKey: undefined}));
											}
										}}
									/>
									<button
										type="button"
										onClick={() => setShowKey(v => !v)}
										className="xy-icon-btn shrink-0 rounded-lg p-2 text-mute hover:bg-paper-deep hover:text-ink"
										aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
										title={showKey ? '隐藏 API Key' : '显示 API Key'}
									>
										{showKey ? (
											<EyeOff className="h-4 w-4" />
										) : (
											<Eye className="h-4 w-4" />
										)}
									</button>
								</div>
								{fieldErrors.apiKey ? (
									<span
										className="mt-1 block text-[11.5px]"
										style={{color: 'var(--xy-danger)'}}
									>
										{fieldErrors.apiKey}
									</span>
								) : null}
							</div>
							<label className="block text-xs">
								<span className="mb-1 block text-mute">API 请求地址</span>
								<input
									className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
									style={
										fieldErrors.baseUrl
											? {borderColor: 'var(--xy-danger)'}
											: undefined
									}
									placeholder="https://your-api-endpoint.com/v1"
									value={draft.baseUrl}
									onChange={e => {
										setDraft(d => ({...d, baseUrl: e.target.value}));
										if (fieldErrors.baseUrl) {
											setFieldErrors(f => ({...f, baseUrl: undefined}));
										}
									}}
								/>
								{fieldErrors.baseUrl ? (
									<span
										className="mt-1 block text-[11.5px]"
										style={{color: 'var(--xy-danger)'}}
									>
										{fieldErrors.baseUrl}
									</span>
								) : null}
							</label>
							<div className="space-y-2">
								<div className="flex items-center justify-between gap-2">
									<span className="text-xs font-medium text-mute">
										模型列表（必填，支持多模型）
									</span>
									<button
										type="button"
										onClick={() =>
											setDraft(d => ({
												...d,
												models: [...d.models, emptyDraftModel()],
											}))
										}
										className="xy-press inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] text-accent hover:bg-accent-soft"
									>
										<Plus className="h-3.5 w-3.5" />
										添加模型
									</button>
								</div>
								{fieldErrors.models ? (
									<span
										className="block text-[11.5px]"
										style={{color: 'var(--xy-danger)'}}
									>
										{fieldErrors.models}
									</span>
								) : null}
								{draft.models.map((m, idx) => {
									const rowBad =
										!!fieldErrors.models &&
										(!m.id.trim() ||
											!(Math.floor(Number(m.contextLimit) || 0) > 0));
									const fieldCls = (bad: boolean) =>
										cn(
											'xy-surface w-full rounded-xl border bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent',
											bad ? 'border' : 'border-line',
										);
									return (
										<div
											key={idx}
											className="space-y-2 rounded-xl border border-line/70 bg-paper-deep/40 p-2.5"
										>
											<div className="grid grid-cols-2 gap-2">
												<label className="block text-xs">
													<span className="mb-1 block text-mute">
														模型 ID（必填）
													</span>
													<input
														className={fieldCls(rowBad)}
														style={
															rowBad
																? {borderColor: 'var(--xy-danger)'}
																: undefined
														}
														placeholder="例如：deepseek-v4-flash"
														value={m.id}
														onChange={e =>
															updateDraftModel(idx, {id: e.target.value})
														}
													/>
												</label>
												<label className="block text-xs">
													<span className="mb-1 block text-mute">
														上下文窗口（token 数，必填）
													</span>
													<input
														type="number"
														min={1}
														className={fieldCls(rowBad)}
														style={
															rowBad
																? {borderColor: 'var(--xy-danger)'}
																: undefined
														}
														placeholder="例如：131072"
														value={m.contextLimit}
														onChange={e =>
															updateDraftModel(idx, {
																contextLimit: e.target.value,
															})
														}
													/>
													<span className="mt-1 block text-[10px] leading-4 text-mute">
														该值将作为后端压力压缩的上下文上限（[XEYO_CONTEXT_LIMIT_TOKENS + RATIO=0.8]）。
													</span>
												</label>
											</div>
											<div className="grid grid-cols-3 gap-2">
												<label className="block text-xs">
													<span className="mb-1 block text-mute">
														最大输出 tokens（可选）
													</span>
													<input
														type="number"
														min={1}
														className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
														placeholder="留空则不限制"
														value={m.maxOutputTokens}
														onChange={e =>
															updateDraftModel(idx, {
																maxOutputTokens: e.target.value,
															})
														}
													/>
												</label>
												<label className="block text-xs">
													<span className="mb-1 block text-mute">输入类型</span>
													<select
														className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
														value={m.inputType}
														onChange={e =>
															updateDraftModel(idx, {
																inputType: e.target.value as DraftModelRow['inputType'],
															})
														}
													>
														<option value="text">文本</option>
														<option value="image">图片</option>
														<option value="video">视频</option>
													</select>
												</label>
												<label className="block text-xs">
													<span className="mb-1 block text-mute">输出类型</span>
													<select
														className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
														value={m.outputType}
														onChange={e =>
															updateDraftModel(idx, {
																outputType: e.target.value as DraftModelRow['outputType'],
															})
														}
													>
														<option value="text">文本</option>
														<option value="image">图片</option>
													</select>
												</label>
											</div>
											<div className="block text-xs">
												<span className="mb-1 block text-mute">思考等级</span>
												<ReasoningLevelsSelect
													value={m.reasoningLevels ?? []}
													onChange={levels =>
														updateDraftModel(idx, {
															reasoningLevels: levels,
															// 默认等级跌出已选集时自动清回「自动」。
															defaultReasoningEffort:
																m.defaultReasoningEffort &&
																levels.includes(m.defaultReasoningEffort)
																	? m.defaultReasoningEffort
																	: '',
														})
													}
												/>
											</div>
											<label className="block text-xs">
												<span className="mb-1 block text-mute">默认等级</span>
												<select
													className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
													value={m.defaultReasoningEffort ?? ''}
													onChange={e =>
														updateDraftModel(idx, {
															defaultReasoningEffort: e.target
																.value as DraftModelRow['defaultReasoningEffort'],
														})
													}
												>
													<option value="">自动</option>
													{(m.reasoningLevels ?? []).length > 0
														? (m.reasoningLevels ?? []).map(level => (
																<option key={level} value={level}>
																	{level}
																</option>
															))
														: REASONING_EFFORTS.map(level => (
																<option key={level} value={level}>
																	{level}
																</option>
															))}
												</select>
												<span className="mt-1 block text-[10px] leading-4 text-mute">
													{(m.reasoningLevels ?? []).length > 0
														? '默认等级限定在已选思考等级内；「自动」沿用会话级设置。'
														: '未限定等级时可选全部；发送时发 reasoning_effort。'}
												</span>
											</label>
											<div className="flex justify-end">
												<button
													type="button"
													onClick={() => removeDraftModel(idx)}
													className="xy-icon-btn inline-flex items-center gap-1 rounded-lg p-1.5 text-mute hover:bg-danger/10 hover:text-danger"
													aria-label="删除此模型"
												>
													<Trash2 className="h-3.5 w-3.5" />
													删除模型
												</button>
											</div>
										</div>
									);
								})}
								<span className="block text-[10px] leading-4 text-mute">
									模型列表在对话输入框上拉选择；每个模型单独登记 ID / 上下文窗口 / 输出上限。
								</span>
							</div>
							<div className="flex justify-end gap-2 pt-1">
								<button
									type="button"
									onClick={() => {
										setShowAdd(false);
										setEditingId(null);
									}}
									className="rounded-lg border border-line px-3 py-1.5 text-xs text-ink-soft hover:text-ink"
								>
									取消
								</button>
								<button
									type="button"
									onClick={saveDraftAccount}
									className="rounded-lg bg-accent px-3 py-1.5 text-xs text-on-accent hover:bg-accent-hover"
								>
									{editingId ? '保存修改' : '保存账号'}
								</button>
							</div>
						</div>
					) : null}

					<ul className="space-y-1.5">
						{profiles.map(p => {
							const active = p.id === activeProfileId;
							const fp = keyFingerprint(p.apiKey);
							return (
								<li key={p.id}>
									<div
										className={cn(
											'flex items-center gap-2 rounded-xl border px-2.5 py-2',
											active
												? 'border-accent/45 bg-accent-soft/70'
												: 'border-line/70 bg-glass-strong',
										)}
									>
										<button
											type="button"
											onClick={() => selectProfile(p.id)}
											className="min-w-0 flex-1 text-left"
										>
											<div className="truncate text-[12px] text-ink">
												{/* 展示用户自己设置的名称；未设置时回退到厂商名。 */}
												{p.name?.trim() || PROVIDER_LABEL[p.provider]}
												{fp ? ` · ${fp}` : ''}
											</div>
											<div className="truncate text-[10px] text-mute">
												{p.name?.trim()
													? `${PROVIDER_LABEL[p.provider]} · `
													: ''}
												{revealedId === p.id && p.apiKey ? (
													<span className="font-mono">{p.apiKey}</span>
												) : fp ? (
													'本机 Key'
												) : (
													'未填 Key'
												)}
												{p.model ? ` · ${profileModelIds(p).length} 个模型` : ''}
											</div>
										</button>
										{p.apiKey ? (
											<button
												type="button"
												onClick={() =>
													setRevealedId(revealedId === p.id ? null : p.id)
												}
												className="xy-icon-btn rounded-lg p-1.5 text-mute hover:bg-paper-deep hover:text-ink"
												aria-label={revealedId === p.id ? '隐藏 API Key' : '显示 API Key'}
												title={revealedId === p.id ? '隐藏 API Key' : '显示 API Key'}
											>
												{revealedId === p.id ? (
													<EyeOff className="h-3.5 w-3.5" />
												) : (
													<Eye className="h-3.5 w-3.5" />
												)}
											</button>
										) : null}
										<button
											type="button"
											onClick={() => openEditAccount(p)}
											className="xy-icon-btn rounded-lg p-1.5 text-mute hover:bg-paper-deep hover:text-ink"
											aria-label="编辑此账号"
											title="编辑此账号"
										>
											<Pencil className="h-3.5 w-3.5" />
										</button>
										{profiles.length > 1 ? (
											<button
												type="button"
												onClick={() => {
													void (async () => {
														const ok = await confirmDialog({
															title: '删除该账号配置？',
															body: `将移除 ${p.name || '此账号'} 的 Key 与模型设置`,
															confirmText: '删除',
															danger: true,
														});
														if (ok) {
															removeProfile(p.id);
														}
													})();
												}}
												className="xy-icon-btn rounded-lg p-1.5 text-mute hover:bg-danger/10 hover:text-danger"
												aria-label="删除此账号"

											>
												<Trash2 className="h-3.5 w-3.5" />
											</button>
										) : null}
									</div>
								</li>
							);
						})}
					</ul>

					<label className="block text-sm">
						<span className="mb-1 block text-mute">
							单次对话 USD 上限（L1.2；留空 = 不限）
						</span>
						<input
							type="number"
							min={0}
							step="0.001"
							value={maxBudgetUsd}
							onChange={e => update({maxBudgetUsd: e.target.value})}
							placeholder="如 0.01"
							className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
						/>
						<span className="mt-1 block text-[11px] leading-snug text-mute">
							每轮按厂商响应 usage 累计；超过上限立即停止并提示「预算超限」。
						</span>
					</label>

					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							网络工具
						</h3>
					</div>
					<label className="block text-sm">
						<span className="mb-1 block text-mute">
							SearXNG 地址（可选）
						</span>
						<input
							type="url"
							value={searxngUrl}
							onChange={e => update({searxngUrl: e.target.value})}
							placeholder="http://127.0.0.1:8080"
							className="xy-surface w-full rounded-xl border border-line bg-glass-strong px-3 py-2 text-ink outline-none focus:border-accent"
						/>
						<span className="mt-1 block text-[11px] leading-snug text-mute">
							自建 SearXNG 的基址；填写后 WebSearch 优先用它。留空则默认
							Bing / Mojeek（需外网确认）。不随安装包内置。
						</span>
					</label>

					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							输出精简
						</h3>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={outputCompact}
						onClick={() => update({outputCompact: !outputCompact})}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
							outputCompact
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">输出精简</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								只删减不改写；代码块、路径、报错原文等原样保留。注入走对话尾部，不影响上下文缓存。
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								outputCompact ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									outputCompact ? 'translate-x-4' : 'translate-x-0',
								)}
							/>
						</span>
					</button>
					{outputCompact ? (
						<>
							<div
								role="radiogroup"
								aria-label="输出精简模式"
								className="grid grid-cols-3 gap-2"
							>
								{(
									[
										{id: 'lite', label: 'Lite'},
										{id: 'full', label: 'Full'},
										{id: 'ultra', label: 'Ultra'},
									] as const
								).map(opt => {
									const active = outputMode === opt.id;
									return (
										<button
											key={opt.id}
											type="button"
											role="radio"
											aria-checked={active}
											onClick={() => update({outputMode: opt.id})}
											className={cn(
												'xy-press rounded-xl border px-3 py-2 text-sm transition-colors',
												active
													? 'border-accent/50 bg-accent-soft text-accent'
													: 'border-line bg-glass-strong text-ink-soft hover:border-line hover:text-ink',
											)}
										>
											{opt.label}
										</button>
									);
								})}
							</div>
							<p className="text-[11px] leading-snug text-mute">
								{outputMode === 'lite'
									? 'Lite：完整语法，只去冗余。'
									: outputMode === 'full'
										? 'Full：碎片短句，长会话输出不递增。'
										: 'Ultra：极简碎片，仅关键信息。'}
							</p>
						</>
					) : null}

					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							写代码精简
						</h3>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={codeCompact}
						onClick={() => update({codeCompact: !codeCompact})}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
							codeCompact
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">写代码精简</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								约束实现体积：少写、多复用；与输出精简独立。注入走对话尾部，关掉不进历史。
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								codeCompact ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									codeCompact ? 'translate-x-4' : 'translate-x-0',
								)}
							/>
						</span>
					</button>
					{codeCompact ? (
						<>
							<div
								role="radiogroup"
								aria-label="写代码精简模式"
								className="grid grid-cols-3 gap-2"
							>
								{(
									[
										{id: 'lite', label: 'Lite'},
										{id: 'full', label: 'Full'},
										{id: 'ultra', label: 'Ultra'},
									] as const
								).map(opt => {
									const active = codeMode === opt.id;
									return (
										<button
											key={opt.id}
											type="button"
											role="radio"
											aria-checked={active}
											onClick={() => update({codeMode: opt.id})}
											className={cn(
												'xy-press rounded-xl border px-3 py-2 text-sm transition-colors',
												active
													? 'border-accent/50 bg-accent-soft text-accent'
													: 'border-line bg-glass-strong text-ink-soft hover:border-line hover:text-ink',
											)}
										>
											{opt.label}
										</button>
									);
								})}
							</div>
							<p className="text-[11px] leading-snug text-mute">
								{codeMode === 'lite'
									? 'Lite：按所求实现；更短做法可点出，仍交付所求。'
									: codeMode === 'full'
										? 'Full：复用梯子 + 最短 diff；禁止顺手扩范围。'
										: 'Ultra：能删不增；只做已明确的需求。'}
							</p>
						</>
					) : null}

					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							上一轮思考回顾
						</h3>
					</div>
					<button
						type="button"
						role="switch"
						aria-checked={reasoningTail}
						onClick={() => update({reasoningTail: !reasoningTail})}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
							reasoningTail
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">
								上一轮思考回顾（建议仅弱模型）
							</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								工具续写轮把上一轮推理结尾注入对话尾部，防弱模型重复思考。强模型不建议；默认关。
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								reasoningTail ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									reasoningTail ? 'translate-x-4' : 'translate-x-0',
								)}
							/>
						</span>
					</button>
				</section>

				<section className={cn('mb-5 space-y-3', activeTab !== 'appearance' && 'hidden')}>
					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							记忆系统开关
						</h3>
					</div>
					<p className="text-[11px] leading-relaxed text-mute">
						持久化到 .xeyo/settings.json 的 memory 段，切换后运行时立即生效（超长会话 C2 灰度即在此）。
					</p>
					<MemorySwitchesSetting />
				</section>

				<section className={cn('mb-5 space-y-3', activeTab !== 'appearance' && 'hidden')}>
					<div className="border-t border-line/60 pt-4">
						<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
							桌面壁纸
						</h3>
					</div>
					<p className="text-[11px] leading-relaxed text-mute">
						各主题均全窗显示。原图至 10MB，保存前压缩并写入本机 IndexedDB。
					</p>

					<div className="overflow-hidden rounded-xl border border-line/80 bg-glass">
						{bgImage ? (
							<div
								className="anim-fade h-28 bg-cover bg-center"
								style={{backgroundImage: `url(${bgImage})`}}
							/>
						) : (
							<div className="flex h-28 items-center justify-center text-sm text-mute">
								未设置背景图
							</div>
						)}
						<div className="flex gap-2 border-t border-line/60 p-2">
							<button
								type="button"
								disabled={compressing}
								onClick={() => fileRef.current?.click()}
								className="xy-press flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-paper-deep/80 py-2 text-xs text-ink hover:bg-accent-soft hover:text-accent disabled:opacity-50"
							>
								<ImagePlus className="h-3.5 w-3.5" />
								{compressing ? '压缩中…' : '选择图片'}
							</button>
							{bgImage ? (
								<button
									type="button"
									onClick={() => update({bgImage: ''})}
									className="xy-press flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs text-mute hover:bg-danger/10 hover:text-danger"
								>
									<Trash2 className="h-3.5 w-3.5" />
									清除
								</button>
							) : null}
						</div>
						<input
							ref={fileRef}
							type="file"
							accept="image/*"
							className="hidden"
							onChange={e => {
								onPickBg(e.target.files?.[0]);
								e.target.value = '';
							}}
						/>
					</div>

					<label className="block text-sm">
						<span className="mb-1 flex justify-between text-mute">
							<span>通透度</span>
							<span className="font-mono text-[11px] tabular-nums">
								{bgOpacity}%
							</span>
						</span>
						<input
							type="range"
							min={0}
							max={100}
							value={bgOpacity}
							onChange={e => update({bgOpacity: Number(e.target.value)})}
							className="w-full accent-accent"
						/>
						<span className="mt-1 block text-[11px] text-mute">
							0% 看不到背景 · 100% 几乎无遮罩、背景最清晰
						</span>
					</label>

					<label className="block text-sm">
						<span className="mb-1 flex justify-between text-mute">
							<span>模糊度</span>
							<span className="font-mono text-[11px] tabular-nums">
								{bgBlur}px
							</span>
						</span>
						<input
							type="range"
							min={0}
							max={40}
							value={bgBlur}
							onChange={e => update({bgBlur: Number(e.target.value)})}
							className="w-full accent-accent"
						/>
					</label>
				</section>

				<section className={cn('mb-5 space-y-3', activeTab !== 'perms' && 'hidden')}>
					<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
						权限
					</h3>
					<p className="text-[12px] leading-relaxed text-mute">
						审批模式（请求批准 / 帮我批准 / 完全访问）在顶栏实时切换，立即对
						本会话生效。下方会话权限 preset 同样支持本会话内实时切换。
					</p>
					<div className="border-t border-line/60 pt-3">
						<RuntimePresetSetting />
					</div>
					<div className="border-t border-line/60 pt-3">
						<h4 className="mb-2 font-sans text-[12px] font-semibold text-ink-soft">
							不再询问（always-allow）
						</h4>
						<GrantsPanel />
					</div>
					<div className="border-t border-line/60 pt-3">
						<BashRoutingSetting />
					</div>
				</section>

				<section className={cn('mb-5 space-y-3', activeTab !== 'rewind' && 'hidden')}>
					<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
						回溯
					</h3>
					<p className="text-[12px] leading-relaxed text-mute">
						默认只恢复本轮 Agent 改过的文件。整树恢复更慢，且可能改写无关文件触发界面热更新。
					</p>
					<button
						type="button"
						role="switch"
						aria-checked={rewindFullTreeRestore}
						onClick={() =>
							update({rewindFullTreeRestore: !rewindFullTreeRestore})
						}
						className={cn(
							'xy-press flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors',
							rewindFullTreeRestore
								? 'border-accent/50 bg-accent-soft'
								: 'border-line bg-glass-strong hover:border-line',
						)}
					>
						<span>
							<span className="block text-sm text-ink">整树工作区恢复</span>
							<span className="mt-0.5 block text-[11px] leading-snug text-mute">
								开启后使用 Shadow Git 整仓恢复到目标提交；关闭时默认按本轮改过的路径做差集恢复（有提交则走 shadow，无提交才用 journal 逆操作）。
							</span>
						</span>
						<span
							className={cn(
								'relative h-5 w-9 shrink-0 rounded-full transition-colors',
								rewindFullTreeRestore ? 'bg-accent' : 'bg-line',
							)}
							aria-hidden
						>
							<span
								className={cn(
									'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
									rewindFullTreeRestore
										? 'translate-x-4'
										: 'translate-x-0',
								)}
							/>
						</span>
					</button>

					<div className="rounded-xl border border-line bg-glass-strong px-3 py-2.5 text-[12px]">
						<h4 className="mb-1 font-sans text-[12px] font-semibold text-ink-soft">
							历史快照清理
						</h4>
						<p className="mb-2 text-[11px] leading-relaxed text-mute">
							回溯时保存的旧版本会被自动去重并跨会话共享。这里控制「保留最近多少份可回退的版本」与「单个对话保存这些历史所占的存储上限」；只有后端开启自动清理、并且超出预算时，才会回收不再需要的旧版本。
						</p>
						<div className="grid grid-cols-2 gap-2">
							<label className="block">
								<span className="mb-1 block text-[10px] text-mute">保留最近几份快照（≥1）</span>
								<input
									type="number"
									min={1}
									value={gcKeepRecentDraft}
									onChange={e => setGcKeepRecentDraft(e.target.value)}
									placeholder="默认 10"
									className="w-full rounded-lg border border-line bg-paper px-2 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
								/>
							</label>
							<label className="block">
								<span className="mb-1 block text-[10px] text-mute">单个对话的存储上限（字节）</span>
								<input
									type="number"
									min={0}
									value={gcMaxBytesDraft}
									onChange={e => setGcMaxBytesDraft(e.target.value)}
									placeholder="留空 = 后端默认"
									className="w-full rounded-lg border border-line bg-paper px-2 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
								/>
							</label>
						</div>
						<p className="mt-2 text-[10px] leading-snug text-mute">
							<span className="text-warn">太小：</span>无法回退较远时点，长任务/大乱局救不回来。
							<span className="text-warn">太大：</span>磁盘与恢复性能占用升高，旧版本拖慢清理与启动扫描。
						</p>
						<button
							type="button"
							onClick={() => void applyGcSettings()}
							className="xy-press mt-2 rounded-lg border border-line px-3 py-1.5 text-[12px] font-medium text-ink transition-colors hover:border-accent/60"
						>
							保存清理设置
						</button>
					</div>
				</section>

				<section className={cn('mb-5 space-y-3', activeTab !== 'remote' && 'hidden')}>
					<h3 className="font-mono text-[10px] uppercase tracking-wider text-mute">
						远程 · 微信
					</h3>
					<p className="text-[12px] leading-relaxed text-mute">
						两种方式并存，同一时刻只启动一种。点右上角二维码启动当前所选通道；回复以
						[XEYO] 开头。切换通道时会断开正在运行的远程。
					</p>
					<div
						role="radiogroup"
						aria-label="远程通道"
						className="grid grid-cols-2 gap-2"
					>
						{(
							[
								{id: 'ilink', label: 'ClawBot / iLink'},
								{id: 'filehelper', label: '文件传输助手'},
							] as const
						).map(opt => {
							const active = remoteChannel === opt.id;
							return (
								<button
									key={opt.id}
									type="button"
									role="radio"
									aria-checked={active}
									onClick={() => {
										if (opt.id === remoteChannel) {
											return;
										}
										const remote = useRemoteStore.getState();
										void (async () => {
											if (remote.state !== 'stopped') {
												await remote.stopRemote();
											}
											update({
												remoteChannel: opt.id as RemoteChannel,
											});
										})();
									}}
									className={cn(
										'xy-press rounded-xl border px-3 py-2.5 text-sm transition-colors',
										active
											? 'border-accent/50 bg-accent-soft text-accent'
											: 'border-line bg-glass-strong text-ink-soft hover:border-line hover:text-ink',
									)}
								>
									{opt.label}
								</button>
							);
						})}
					</div>
					{remoteChannel === 'ilink' ? (
						<>
							<p className="text-[12px] leading-relaxed text-mute">
								不依赖手机里的「插件」入口，也不安装 OpenClaw。点顶栏二维码后，用微信扫描
								XEYO 弹出的码并确认。支持私聊文字、图片和文件。截图由 Screenshot 工具完成；连上远程时会在后台发一份到微信，不阻塞模型。
							</p>
							<p className="text-[12px] leading-relaxed text-ink-soft">
								验收：设置里选本通道 → 填 API Key → 点顶栏二维码 →
								手机微信扫码确认 → 给该 Bot 发「你好」→ 桌面当前对话出现
								[远程] 气泡，回复回到微信。若接口报灰度/风控，面板会显示
								errmsg，可改回文件传输助手。
							</p>
						</>
					) : (
						<>
							<p className="text-[12px] leading-relaxed text-mute">
								XEYO 在后台打开官方网页并显示二维码。用手机微信扫码后，发给「文件传输助手」的文字会驱动当前对话。浏览器窗口不会弹出。
							</p>
							<p className="text-[12px] leading-relaxed text-ink-soft">
								需要本机已安装 Playwright：
								<code className="mx-1 font-mono text-[11px]">
									pip install playwright mss
								</code>
								后执行
								<code className="mx-1 font-mono text-[11px]">
									playwright install chromium
								</code>
							</p>
						</>
					)}
					<ul className="space-y-1 font-mono text-[11px] text-ink-soft">
						<li>/help · 帮助 — 指令列表（远程统一入口）</li>
						<li>/status · 状态 — 连接与任务</li>
						<li>/cwd · 目录 — 当前工作区路径</li>
						<li>/stop · 停止 — 中断正在跑的任务</li>
						<li>/allow · 允许 / /deny · 拒绝 — 处理待批准操作</li>
						<li>/rule · /doctor · /proposals — 工作区 XEYO.md 规则</li>
						<li>截图 — 直接说「截图」，由 Screenshot 工具交给模型查看</li>
					</ul>
				</section>

					</div>
				</div>

			</div>
		</div>
	);
}
