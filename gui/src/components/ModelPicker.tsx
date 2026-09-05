import {Check, Search} from 'lucide-react';
import {
	useEffect,
	useLayoutEffect,
	useMemo,
	useState,
	type RefObject,
} from 'react';
import {createPortal} from 'react-dom';
import {allowsEmptyApiKey} from '@/lib/localTestGate';
import {cn} from '@/lib/utils';
import {
	PROVIDER_LABEL,
	keyFingerprint,
	profileModelIds,
	useSettingsStore,
	type ModelProfile,
	type ProviderId,
} from '@/stores/settingsStore';

const FLYOUT = 'xy-menu-flyout rounded-xl';

type Props = {
	open: boolean;
	menuId: string;
	disabled?: boolean;
	/** 编辑历史气泡时把飞出层挂到 body，避免被消息滚动容器裁剪。 */
	portal?: boolean;
	anchorRef?: RefObject<HTMLElement | null>;
	/** 会话输入框手动选的思考等级；与 onReasoningEffortChange 成对提供时，
	 *  面板左栏底部显示「思考等级」分段选择（老版 ModelPicker 样式）。 */
	reasoningEffort?: string;
	onReasoningEffortChange?: (v: string) => void;
};

export function ModelPicker({
	open,
	menuId,
	disabled,
	portal = false,
	anchorRef,
	reasoningEffort,
	onReasoningEffortChange,
}: Props) {
	const model = useSettingsStore(s => s.model);
	const provider = useSettingsStore(s => s.provider);
	const apiKey = useSettingsStore(s => s.apiKey);
	const baseUrl = useSettingsStore(s => s.baseUrl);
	const profiles = useSettingsStore(s => s.profiles) ?? [];
	const activeProfileId = useSettingsStore(s => s.activeProfileId);
	const selectProfile = useSettingsStore(s => s.selectProfile);
	const update = useSettingsStore(s => s.update);
	const openSettings = useSettingsStore(s => s.openSettings);

	const accounts = useMemo(() => {
		// 空 Key 仅允许本地测试 provider（localTestGate，T25c）。
		const withKey = profiles.filter(p => p.apiKey.trim() || allowsEmptyApiKey(p.provider));
		if (withKey.length > 0) {
			return withKey;
		}
		if (apiKey.trim()) {
			return [
				{
					id: activeProfileId || 'current',
					provider,
					model,
					apiKey,
					baseUrl,
				} satisfies ModelProfile,
			];
		}
		return [];
	}, [profiles, apiKey, provider, model, baseUrl, activeProfileId]);

	const [hoverAccountId, setHoverAccountId] = useState<string | null>(null);

	const [query, setQuery] = useState('');

	useEffect(() => {
		if (!open) {
			setHoverAccountId(null);

			setQuery('');
			return;
		}
		setHoverAccountId(
			prev => prev ?? (activeProfileId || accounts[0]?.id || null),
		);
	}, [open, activeProfileId, accounts]);

	const hoverAccount = accounts.find(a => a.id === hoverAccountId);

	/* 模型候选改为「各 profile 里用户登记的模型集合」展平得到；不再从厂商 GET /models 拉取。
	   无模型时给占位提示，引导用户先到设置里登记模型。 */
	const models = useMemo(() => {
		if (!hoverAccount) {
			return [];
		}
		const ids = profileModelIds(hoverAccount);
		const q = query.trim().toLowerCase();
		const filtered = q
			? ids.filter(id => id.toLowerCase().includes(q))
			: ids;
		return filtered.slice(0, q ? 40 : 5);
	}, [hoverAccount, query]);

	const pickModel = (account: ModelProfile, mid: string) => {
		if (account.id !== activeProfileId) {
			selectProfile(account.id);
		}
		update({
			provider: account.provider as ProviderId,
			model: mid,
			apiKey: account.apiKey,
			baseUrl: account.baseUrl,
		});
	};

	// 活动模型在设置里勾选的思考等级——面板只列这些（不再回退全量）；
	// 未勾选 = 该模型未限定等级，面板仅显示「自动」。
	const activeModelLevels = useSettingsStore(s => {
		const p = s.profiles.find(pp => pp.id === s.activeProfileId);
		return p?.models?.find(mm => mm.id === s.model)?.reasoningLevels;
	});
	const levelOptions = useMemo(
		() => activeModelLevels ?? [],
		[activeModelLevels],
	);

	const [portalPosition, setPortalPosition] = useState<{
		right: number;
		top?: number;
		bottom?: number;
		placement: 'above' | 'below';
		maxHeight: number;
	} | null>(null);

	useLayoutEffect(() => {
		if (!portal || !open || typeof window === 'undefined') {
			setPortalPosition(null);
			return;
		}
		const anchor = anchorRef?.current;
		if (!anchor) {
			setPortalPosition(null);
			return;
		}
			const updatePosition = () => {
				const rect = anchor.getBoundingClientRect();
				const gap = 8;
				const availableAbove = Math.max(0, rect.top - gap);
				const availableBelow = Math.max(0, window.innerHeight - rect.bottom - gap);
				const placement = availableBelow > availableAbove ? 'below' : 'above';
				setPortalPosition({
					right: Math.max(8, window.innerWidth - rect.right),
					placement,
					maxHeight: Math.max(
						1,
						Math.floor(placement === 'below' ? availableBelow : availableAbove),
					),
					...(placement === 'below'
						? {top: Math.max(8, rect.bottom + 2)}
						: {bottom: Math.max(8, window.innerHeight - rect.top + 2)}),
				});
			};
		updatePosition();
		window.addEventListener('resize', updatePosition);
		window.addEventListener('scroll', updatePosition, true);
		return () => {
			window.removeEventListener('resize', updatePosition);
			window.removeEventListener('scroll', updatePosition, true);
		};
	}, [anchorRef, open, portal]);

	if (!open) {
		return null;
	}

	const menu = (
		<div
			id={menuId}
			className={cn(
				portal ? 'fixed' : 'absolute',
					'right-0 z-[1000]',
					portalPosition?.placement === 'below'
						? 'top-full mt-1.5'
						: 'bottom-full mb-1.5',
			)}
			style={
				portal && portalPosition
						? {
								right: portalPosition.right,
								...(portalPosition.placement === 'below'
									? {top: portalPosition.top}
									: {bottom: portalPosition.bottom}),
								maxWidth: 'calc(100vw - 1rem)',
								maxHeight: portalPosition.maxHeight,
								overflowY: 'auto',
						  }
						: undefined
			}
		>

		<div className={cn(FLYOUT, 'flex overflow-hidden')}>
			{/* 尺寸固定：两栏等高，切账号不改总高度，避免底部锚定的菜单移动导致行抖动闪烁。
			    带思考等级区时整体加高，等级行用 3 列网格。 */}
			<div
				className={cn(
					'flex w-[17.5rem] flex-col border-r border-line/40',
					onReasoningEffortChange ? 'h-[21rem]' : 'h-[16.5rem]',
				)}
			>
				{hoverAccount ? (
					<>
						<div className="px-2.5 pt-2.5">
							<label className="flex h-8 items-center gap-2 rounded-lg bg-ink/[0.06] px-2.5">
								<Search className="h-3.5 w-3.5 shrink-0 text-mute" />
								<input
									value={query}
									onChange={e => setQuery(e.target.value)}
									placeholder="Search models"
									className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-mute"
								/>
							</label>
						</div>
						<div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
							{models.length === 0 ? (
								<p className="px-2 py-3 text-[12px] leading-relaxed text-mute">
									该账号尚未登记模型，请先在设置里添加模型。
								</p>
							) : (
								models.map(opt => {
									const active =
										opt === model &&
										hoverAccount.provider === provider;
									return (
										<button
											key={opt}
											type="button"

											onClick={() => pickModel(hoverAccount, opt)}
											className={cn(
												'xy-menu-row flex w-full items-center gap-2 px-2.5 py-2 text-left',
												active && 'is-active',

											)}
										>
											<span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink">
												{opt}
											</span>
											{active ? (
												<Check
													className="h-3.5 w-3.5 shrink-0 text-accent"
													strokeWidth={2.4}
												/>
											) : null}
										</button>
									);
								})
							)}
						</div>
						{onReasoningEffortChange ? (
							<div className="border-t border-line/40 px-2.5 pb-2 pt-2">
								<div className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.08em] text-mute">
									思考等级
								</div>
								<div className="grid grid-cols-3 gap-1.5">
									{levelOptions.map(level => (
										<button
											key={level}
											type="button"
											onClick={() =>
												// 再点一次已选等级 = 取消，回到自动（模型默认/会话级）。
												onReasoningEffortChange(
													reasoningEffort === level ? '' : level,
												)
											}
											className={cn(
												'whitespace-nowrap rounded-lg border border-line/60 px-2 py-1.5 font-mono text-[11.5px] text-mute transition-colors hover:border-accent/40 hover:text-ink',
												reasoningEffort === level &&
													'border-accent/50 bg-accent/12 text-accent',
											)}
										>
											{level}
										</button>
									))}
								</div>
								{levelOptions.length === 0 ? (
									<div className="mt-1.5 text-[10px] leading-4 text-mute">
										该模型未在设置中勾选思考等级
									</div>
								) : null}
							</div>
						) : null}
						<div className="border-t border-line/40 px-2.5 py-2.5">
							<div className="text-[10px] uppercase tracking-[0.08em] text-mute">
								{models.length} 个已登记模型
							</div>
						</div>
					</>
				) : (
					<p className="px-4 py-8 text-[12px] text-mute">
						将鼠标移到右侧厂商上查看模型
					</p>
				)}
			</div>

			<div
				className={cn(
					'flex w-[14.25rem] flex-col',
					onReasoningEffortChange ? 'h-[21rem]' : 'h-[16.5rem]',
				)}
			>
				<div className="px-3 pb-1 pt-2.5 text-[10px] font-medium uppercase tracking-[0.08em] text-mute">
					已添加厂商
				</div>
				<div className="min-h-0 flex-1 overflow-y-auto px-1.5">
					{accounts.length === 0 ? (
						<p className="px-2 py-3 text-[12px] leading-relaxed text-mute">
							还没有账号。请先在设置中添加服务商和 API Key。
						</p>
					) : (
						accounts.map(acc => {
							const active = acc.id === hoverAccount?.id;
							const fp = keyFingerprint(acc.apiKey);
							// 展示用户自己设置的名称；未设置时回退到厂商名。
							const accLabel = acc.name?.trim() || PROVIDER_LABEL[acc.provider];
							const letter = accLabel.slice(0, 1);
							return (
								<button
									key={acc.id}
									type="button"
									disabled={disabled}
									onMouseEnter={() => {
										setHoverAccountId(acc.id);

										setQuery('');
									}}
									onClick={() => {
										setHoverAccountId(acc.id);
										selectProfile(acc.id);
									}}
									className={cn(
										'xy-menu-row flex w-full items-center gap-2.5 px-2 py-1.5 text-left',
										active && 'is-active',
									)}
								>
									<span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-ink/[0.08] text-[11px] font-medium text-ink-soft">
										{letter}
									</span>
									<span className="min-w-0 flex-1">
										<span className="block truncate text-[12.5px] text-ink">
											{accLabel}
										</span>
										{fp ? (
											<span className="block truncate font-mono text-[10px] text-mute">
												{fp}
											</span>
										) : null}
									</span>
								</button>
							);
						})
					)}
				</div>
				<button
					type="button"
					onClick={() => openSettings('accounts')}
					className="xy-menu-row mx-1.5 mb-1.5 px-2.5 py-2 text-left text-[12.5px] text-ink-soft"
				>
					添加账号
				</button>
			</div>
		</div>
		</div>
	);
	return portal
		? portalPosition
			? createPortal(menu, document.body)
			: null
		: menu;
}
