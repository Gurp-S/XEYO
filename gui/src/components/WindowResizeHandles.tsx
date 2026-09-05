import {isTauri} from '@/lib/tauri';

type ResizeDirection =
	| 'East'
	| 'North'
	| 'NorthEast'
	| 'NorthWest'
	| 'South'
	| 'SouthEast'
	| 'SouthWest'
	| 'West';

const EDGES: {dir: ResizeDirection; className: string}[] = [
	{dir: 'South', className: 'bottom-0 left-2 right-2 h-1.5 cursor-s-resize'},
	{dir: 'West', className: 'left-0 top-2 bottom-2 w-1.5 cursor-w-resize'},
	{dir: 'East', className: 'right-0 top-2 bottom-2 w-1.5 cursor-e-resize'},
	{dir: 'SouthWest', className: 'left-0 bottom-0 h-3 w-3 cursor-sw-resize'},
	{dir: 'SouthEast', className: 'right-0 bottom-0 h-3 w-3 cursor-se-resize'},
];

async function startResize(dir: ResizeDirection) {
	const {getCurrentWindow} = await import('@tauri-apps/api/window');
	await getCurrentWindow().startResizeDragging(dir);
}

/** 边缘命中区域，使无装饰窗口可通过拖拽边缘调整大小。 */
export function WindowResizeHandles() {
	if (!isTauri()) {
		return null;
	}

	return (
		<div className="pointer-events-none absolute inset-0 z-20" aria-hidden>
			{EDGES.map(({dir, className}) => (
				<div
					key={dir}
					className={`pointer-events-auto absolute ${className}`}
					onMouseDown={e => {
						e.preventDefault();
						void startResize(dir);
					}}
				/>
			))}
		</div>
	);
}
