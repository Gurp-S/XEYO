/**
 * T10：always-allow 授权（"don't ask again"）管理面板。
 * 列出 grant store 条目（tool + 前缀/规则指纹 + 工作区 + 过期时间），可撤销。
 */
import {useCallback, useEffect, useState} from 'react';
import {RefreshCw, Trash2} from 'lucide-react';
import {
	listPermissionGrants,
	revokePermissionGrant,
	type PermissionGrantInfo,
} from '@/lib/api';
import {confirmDialog} from '@/lib/inlineDialog';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';

function fmtExpiry(expiresAt: number | null): string {
	if (!expiresAt) return '不过期';
	const left = expiresAt - Date.now() / 1000;
	if (left <= 0) return '已过期（待清理）';
	const h = Math.floor(left / 3600);
	if (h >= 1) return `剩 ${h} 小时`;
	return `剩 ${Math.max(1, Math.floor(left / 60))} 分钟`;
}

function shortScope(scope: string): string {
	if (!scope) return '（全局）';
	const parts = scope.replace(/[\\/]+$/, '').split(/[\\/]/);
	return parts[parts.length - 1] || scope;
}

export function GrantsPanel() {
	const [grants, setGrants] = useState<PermissionGrantInfo[]>([]);
	const [loading, setLoading] = useState(false);

	const reload = useCallback(async () => {
		setLoading(true);
		try {
			setGrants(await listPermissionGrants());
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void reload();
	}, [reload]);

	const revoke = async (g: PermissionGrantInfo) => {
		const ok = await confirmDialog({
			title: '撤销该授权？',
			body: `撤销后，${g.tool_name} · ${g.fingerprint} 在 ${shortScope(g.scope)} 会重新走审批。`,
			confirmText: '撤销',
			danger: true,
		});
		if (!ok) return;
		if (await revokePermissionGrant(g.grant_id)) {
			toast.success('已撤销授权');
			void reload();
		} else {
			toast.error('撤销失败，请重试');
		}
	};

	return (
		<div className="space-y-2">
			<div className="flex items-center justify-between">
				<p className="text-[11px] leading-relaxed text-mute">
					审批面板勾选「不再询问」后记在这里；按 工具 + 命令前缀 + 工作区 生效，到期自动失效。只放行本会被拦下询问的操作，黑名单与硬保护不受影响。
				</p>
				<button
					type="button"
					onClick={() => void reload()}
					className="xy-icon-btn shrink-0 rounded-lg p-1.5 text-mute hover:bg-paper-deep hover:text-ink"
					aria-label="刷新"
				>
					<RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
				</button>
			</div>
			{!loading && grants.length === 0 ? (
				<div className="rounded-xl border border-line/70 bg-glass-strong px-3 py-4 text-center text-[12px] text-mute">
					暂无授权。审批时勾选「不再询问此类命令」即可保存到这里。
				</div>
			) : null}
			<ul className="space-y-1.5">
				{grants.map(g => (
					<li
						key={g.grant_id}
						className="flex items-center gap-2 rounded-xl border border-line/70 bg-glass-strong px-2.5 py-2"
					>
						<div className="min-w-0 flex-1">
							<div className="truncate font-mono text-[12px] text-ink">
								{g.tool_name} · {g.fingerprint}
							</div>
							<div className="truncate text-[10px] text-mute">
								{shortScope(g.scope)} · {fmtExpiry(g.expires_at)}
								{g.actor ? ` · by ${g.actor}` : ''}
							</div>
						</div>
						<button
							type="button"
							onClick={() => void revoke(g)}
							className="xy-icon-btn rounded-lg p-1.5 text-mute hover:bg-danger/10 hover:text-danger"
							aria-label="撤销此授权"
						>
							<Trash2 className="h-3.5 w-3.5" />
						</button>
					</li>
				))}
			</ul>
		</div>
	);
}
