import {useEffect, useState} from 'react';
import {readWorkspaceFile} from '@/lib/api';
import {normalizePath, samePath} from '@/lib/paths';
import {useChatStore} from '@/stores/chatStore';

const cache = new Map<string, string>();

function activeWorkspaceRoot(): string {
	const state = useChatStore.getState();
	return state.spaces.find(space => space.id === state.activeSpaceId)?.rootPath?.trim() ?? '';
}

type Props = {
	path: string;
	alt: string;
};

export function WorkspaceImg({path, alt}: Props) {
	const root = useChatStore(s => {
		const space = s.spaces.find(item => item.id === s.activeSpaceId);
		return space?.rootPath?.trim() ?? '';
	});
	const cacheKey = `${normalizePath(root)}\u0000${path}`;
	const [loaded, setLoaded] = useState(() => ({
		key: cacheKey,
		src: cache.get(cacheKey) ?? '',
	}));
	const src = loaded.key === cacheKey ? loaded.src : '';

	useEffect(() => {
		const cached = cache.get(cacheKey);
		if (cached) {
			setLoaded({key: cacheKey, src: cached});
			return;
		}
		setLoaded({key: cacheKey, src: ''});
		if (!root) return;
		let alive = true;
		void readWorkspaceFile(path, root)
			.then(doc => {
				const url = doc.data_url || '';
				if (
					!url ||
					!alive ||
					!samePath(activeWorkspaceRoot(), root)
				) {
					return;
				}
				cache.set(cacheKey, url);
				setLoaded({key: cacheKey, src: url});
			})
			.catch(() => {
				/* 保持占位 */
			});
		return () => {
			alive = false;
		};
	}, [cacheKey, path, root]);

	if (!src) {
		return <span className="text-mute">{alt || '[image]'}</span>;
	}
	return (
		<img
			src={src}
			alt={alt}
			className="my-2 max-h-[28rem] max-w-full rounded-lg border border-line/50"
		/>
	);
}
