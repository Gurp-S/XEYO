import { loadConfig } from './loader.js';

export function createApp(raw) {
  const config = loadConfig(raw);
  return { config, url: `http://${config.host}:${config.port}`, mode: config.retries > 0 ? 'retry' : 'once' };
}
