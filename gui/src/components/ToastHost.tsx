import {X} from 'lucide-react';
import {useEffect, useState, useSyncExternalStore, type CSSProperties} from 'react';
import {toast, type ToastItem} from '@/lib/toast';
import './ux-toast.css';

const KIND_COLOR: Record<ToastItem['kind'], string> = {
	success: 'var(--xy-ok)',
	error: 'var(--xy-danger)',
	warn: 'var(--xy-warn)',
	info: 'var(--xy-accent)',
};

/** 略大于 140ms 出场过渡，动画播完再卸载 */
const EXIT_MS = 160;

type Row = {item: ToastItem; leaving: boolean};

function ToastRow({row}: {row: Row}) {
	const [entered, setEntered] = useState(false);
	const isError = row.item.kind === 'error';

	// 双 rAF 确保初始态先绘制，再切 is-in 播放入场过渡
	useEffect(() => {
		let raf2 = 0;
		const raf1 = requestAnimationFrame(() => {
			raf2 = requestAnimationFrame(() => setEntered(true));
		});
		return () => {
			cancelAnimationFrame(raf1);
			cancelAnimationFrame(raf2);
		};
	}, []);

	return (
		<div
			className={`xy-toast${entered && !row.leaving ? ' is-in' : ''}`}
			style={{'--toast-c': KIND_COLOR[row.item.kind]} as CSSProperties}
			role={isError ? 'alert' : 'status'}
			aria-live={isError ? 'assertive' : 'polite'}
		>
			<span className="xy-toast-msg">{row.item.msg}</span>
			{row.item.action ? (
				<button
					type="button"
					className="xy-toast-action"
					onClick={() => {
						toast.dismiss(row.item.id);
						row.item.action?.onClick();
					}}
				>
					{row.item.action.label}
				</button>
			) : null}
			<button
				type="button"
				className="xy-toast-close"
				aria-label="关闭通知"
				onClick={() => toast.dismiss(row.item.id)}
			>
				<X className="size-3.5" />
			</button>
			<span className="xy-toast-progress" aria-hidden>
				<span
					className="xy-toast-progress-fill"
					style={{animationDuration: `${row.item.duration}ms`}}
				/>
			</span>
		</div>
	);
}

/**
 * 全局 Toast 宿主：挂载于 App 根（路由之外）。
 * store 条目消失时先标记 leaving 播出场动画，再从本地行列表卸载。
 */
export function ToastHost() {
	const items = useSyncExternalStore(toast._sub, toast._items);
	const [rows, setRows] = useState<Row[]>([]);

	useEffect(() => {
		setRows(prev => {
			const liveIds = new Set(items.map(i => i.id));
			const knownIds = new Set(prev.map(r => r.item.id));
			let changed = false;
			const next: Row[] = [];
			for (const r of prev) {
				if (!liveIds.has(r.item.id)) {
					changed = true;
					next.push(r.leaving ? r : {...r, leaving: true});
				} else {
					next.push(r);
				}
			}
			for (const it of items) {
				if (!knownIds.has(it.id)) {
					changed = true;
					next.push({item: it, leaving: false});
				}
			}
			return changed ? next : prev;
		});
	}, [items]);

	useEffect(() => {
		const leavingIds = rows.filter(r => r.leaving).map(r => r.item.id);
		if (leavingIds.length === 0) {
			return;
		}
		const ids = new Set(leavingIds);
		const t = window.setTimeout(() => {
			setRows(prev => prev.filter(r => !ids.has(r.item.id)));
		}, EXIT_MS);
		return () => window.clearTimeout(t);
	}, [rows]);

	return (
		<div className="xy-toast-host">
			{rows.map(row => (
				<ToastRow key={row.item.id} row={row} />
			))}
		</div>
	);
}
