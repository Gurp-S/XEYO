import {isLocalTestEnabled} from './localTestGate';

export function isRetiredLocalProvider(provider: unknown): boolean {
	return provider === 'local' && !isLocalTestEnabled();
}

type Connection = {provider: string; model: string; apiKey: string; baseUrl: string};

/** Discard retired accounts without carrying their endpoint into a cloud profile. */
export function retireLocalModelSettings<T extends Connection & {profiles?: unknown}>(
	settings: T,
	defaults: Connection,
): T {
	if (isLocalTestEnabled()) return settings;
	const profiles = Array.isArray(settings.profiles)
		? settings.profiles.filter(row => !isRetiredLocalProvider(row?.provider))
		: settings.profiles;
	const connection = isRetiredLocalProvider(settings.provider)
		? {provider: defaults.provider, model: defaults.model, apiKey: defaults.apiKey, baseUrl: defaults.baseUrl}
		: {};
	return {...settings, ...connection, profiles};
}
