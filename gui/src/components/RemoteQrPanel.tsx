import {memo, useEffect, useState} from 'react';
import {Loader2, QrCode, Smartphone, X} from 'lucide-react';
import {usePresence} from '@/hooks/usePresence';
import {cn} from '@/lib/utils';
import {remoteQrUrl, useRemoteStore} from '@/stores/remoteStore';
import {useSettingsStore} from '@/stores/settingsStore';

const STEPS = [
	{id: 'starting', label: '连接'},
	{id: 'qr', label: '扫码'},
	{id: 'scanned', label: '确认'},
] as const;

function stepIndex(state: string) {
	if (state === 'scanned') {
		return 2;
	}
	if (state === 'qr') {
		return 1;
	}
	return 0;
}

function QrFrame({qrRev, alt}: {qrRev: number; alt: string}) {
	const url = remoteQrUrl(qrRev);
	const [src, setSrc] = useState(url);

	useEffect(() => {
		const img = new Image();
		img.onload = () => setSrc(url);
		img.src = url;
		return () => {
			img.onload = null;
		};
	}, [url]);

	return (
		<img
			src={src}
			alt={alt}
			className="h-[216px] w-[216px] rounded-lg object-contain"
			onError={() => {
				void useRemoteStore.getState().pollRemote();
			}}
		/>
	);
}

const RemoteQrPanelBody = memo(function RemoteQrPanelBody({
	shown,
}: {
	shown: boolean;
}) {
	const state = useRemoteStore(s => s.state);
	const hasQr = useRemoteStore(s => s.hasQr);
	const error = useRemoteStore(s => s.error);
	const hint = useRemoteStore(s => s.hint);
	const qrRev = useRemoteStore(s => s.qrRev);
	const busy = useRemoteStore(s => s.busy);
	const stopRemote = useRemoteStore(s => s.stopRemote);
	const remoteChannel = useSettingsStore(s => s.remoteChannel);
	const ilink = remoteChannel === 'ilink';

	const title =
		state === 'scanned'
			? '请在手机上确认'
			: state === 'error'
				? '远程启动失败'
				: state === 'qr'
					? '扫描二维码'
					: '正在连接微信';

	const showQr = hasQr && (state === 'qr' || state === 'starting');
	const waiting =
		!showQr &&
		(busy || state === 'starting' || (state === 'qr' && !hasQr));
	const activeStep = stepIndex(state);
	const failed = state === 'error';

	return (
		<div
			className={cn(
				'xy-modal-backdrop pointer-events-none fixed inset-0 z-[100] flex items-center justify-center p-4',
				shown ? 'opacity-100' : 'opacity-0',
			)}
		>
			<div
				role="dialog"
				aria-modal="true"
				aria-label={title}
				className={cn(
					'xy-modal-panel xy-modal-elevated pointer-events-auto w-full max-w-[360px] rounded-2xl border border-line/80 bg-paper p-5',
					shown
						? 'translate-y-0 scale-100 opacity-100'
						: 'translate-y-2 scale-[0.98] opacity-0',
				)}
			>
				<div className="mb-4 flex items-start justify-between gap-3">
					<div className="flex min-w-0 items-center gap-3">
						<div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
							{state === 'scanned' ? (
								<Smartphone className="h-4 w-4" />
							) : (
								<QrCode className="h-4 w-4" />
							)}
						</div>
						<div className="min-w-0">
							<h2 className="font-sans text-[15px] font-semibold text-ink">
								{title}
							</h2>
							<p className="mt-0.5 text-[11px] leading-relaxed text-mute">
								{ilink
									? '微信扫码确认（不是文件助手网页）'
									: '用手机微信扫码，登录「文件传输助手」'}
							</p>
						</div>
					</div>
					<button
						type="button"
						onClick={() => void stopRemote()}
						className="xy-icon-btn shrink-0 rounded-xl p-1.5 text-mute hover:bg-paper-deep hover:text-ink"
						
					>
						<X className="h-4 w-4" />
					</button>
				</div>

				<ol className="mb-4 flex items-center gap-1">
					{STEPS.map((step, i) => {
						const on = !failed && i <= activeStep;
						const current = !failed && i === activeStep;
						return (
							<li key={step.id} className="flex min-w-0 flex-1 items-center gap-1">
								<span
									className={cn(
										'flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px]',
										on
											? 'bg-accent text-on-accent'
											: 'bg-paper-deep text-mute',
									)}
								>
									{i + 1}
								</span>
								<span
									className={cn(
										'truncate text-[11px]',
										current ? 'text-ink' : 'text-mute',
									)}
								>
									{step.label}
								</span>
								{i < STEPS.length - 1 ? (
									<span
										className={cn(
											'mx-0.5 h-px min-w-3 flex-1',
											i < activeStep && !failed ? 'bg-accent/50' : 'bg-line',
										)}
									/>
								) : null}
							</li>
						);
					})}
				</ol>

				<div
					className="relative flex min-h-[248px] items-center justify-center overflow-hidden rounded-2xl"
					style={{
						background: '#f7f7f8',
						boxShadow: 'inset 0 0 0 1px rgb(18 22 28 / 0.06)',
					}}
				>
					{showQr ? (
						<QrFrame
							qrRev={qrRev}
							alt={ilink ? 'ClawBot / iLink 登录二维码' : '微信登录二维码'}
						/>
					) : (
						<div className="flex flex-col items-center gap-3 px-6 text-center">
							{waiting && !failed ? (
								<Loader2 className="h-7 w-7 animate-spin text-accent" />
							) : null}
							<p className="font-sans text-[13px] text-ink-soft">
								{state === 'scanned'
									? '已扫码，请在手机上点确认'
									: failed
										? '无法获取二维码'
										: '正在获取二维码…'}
							</p>
						</div>
					)}
				</div>

				{error ? (
					<p className="mt-3 rounded-xl bg-danger/10 px-3 py-2 text-[12px] leading-relaxed text-danger">
						{error}
					</p>
				) : hint ? (
					<p className="mt-3 text-[12px] leading-relaxed text-mute">{hint}</p>
				) : null}
			</div>
		</div>
	);
});

/** 已登录或未打开时只订 panelOpen/state，避免流式/QR 字段拖着整面板重渲染。 */
export const RemoteQrPanel = memo(function RemoteQrGate() {
	const panelOpen = useRemoteStore(s => s.panelOpen);
	const state = useRemoteStore(s => s.state);
	const open = panelOpen && state !== 'logged_in' && state !== 'stopped';
	const {mounted, shown} = usePresence(open, 80, 1);

	if (!mounted) {
		return null;
	}

	return <RemoteQrPanelBody shown={shown} />;
});
