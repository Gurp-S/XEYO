import {useMemo} from 'react';
import {Map} from 'lucide-react';
import {parseXeyoMapFence} from '@/lib/xeyoMapFence';
import {useCodeMapStore} from '@/stores/codeMapStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';

type Props = {source: string};

/** 对话里的 ```xeyo-map 围栏：校验后推入地图，并提供一键打开。 */
export function XeyoMapFence({source}: Props) {
	const doc = useMemo(() => parseXeyoMapFence(source), [source]);
	const setAuthored = useCodeMapStore(s => s.setAuthored);

	// 不在 effect 里自动 setAuthored（doc 对象会触发更新环）；
	// 仅在用户点击时推入地图。

	if (!doc) {
		return (
			<pre className="overflow-auto border border-line/40 bg-glass p-2 font-mono text-[11px] text-mute">
				invalid xeyo-map
			</pre>
		);
	}

	const open = () => {
		setAuthored(doc);
		useWorkspaceStore.getState().setOpen(true);
		useWorkspaceStore.getState().setActiveTool('map');
	};

	return (
		<button type="button" onClick={open} className="xy-agent-map-fence">
			<Map className="h-4 w-4 shrink-0 text-accent" />
			<span className="min-w-0 flex-1">
				<span className="xy-agent-map-fence__title">
					{doc.title || `${doc.kind} map`}
				</span>
				<span className="xy-agent-map-fence__meta">
					{doc.kind} · {doc.nodes.length}n/{doc.edges.length}e · open map
				</span>
			</span>
		</button>
	);
}
