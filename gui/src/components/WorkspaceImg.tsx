import {useEffect, useState} from 'react';
import {readWorkspaceFile} from '@/lib/api';

const cache = new Map<string, string>();

type Props = {
	path: string;
	alt: string;
};

export function WorkspaceImg({path, alt}: Props) {
	const [src, setSrc] = useState(() => cache.get(path) ?? '');

	useEffect(() => {
		if (cache.has(path)) {
			setSrc(cache.get(path) ?? '');
			return;
		}
		let alive = true;
		void readWorkspaceFile(path)
			.then(doc => {
				const url = doc.data_url || '';
				if (!url || !alive) {
					return;
				}
				cache.set(path, url);
				setSrc(url);
			})
			.catch(() => {
				/* 保持占位 */
			});
		return () => {
			alive = false;
		};
	}, [path]);

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
