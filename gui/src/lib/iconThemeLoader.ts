import {useEffect, useState} from 'react';

type IconThemeModule = typeof import('react-material-icon-theme');

let loaderPromise: Promise<IconThemeModule> | null = null;

export function loadIconTheme(): Promise<IconThemeModule> {
	if (!loaderPromise) {
		loaderPromise = import('react-material-icon-theme').catch((err: unknown) => {
			loaderPromise = null;
			throw err;
		});
	}
	return loaderPromise;
}

if (typeof window !== 'undefined') {
	const preload = () => {
		void loadIconTheme().catch(() => undefined);
	};
	if (typeof window.requestIdleCallback === 'function') {
		window.requestIdleCallback(preload);
	} else {
		window.setTimeout(preload, 1500);
	}
}

export function useIconTheme(): IconThemeModule | null {
	const [mod, setMod] = useState<IconThemeModule | null>(null);
	useEffect(() => {
		let active = true;
		loadIconTheme()
			.then(m => {
				if (active) {
					setMod(m);
				}
			})
			.catch(() => undefined);
		return () => {
			active = false;
		};
	}, []);
	return mod;
}
