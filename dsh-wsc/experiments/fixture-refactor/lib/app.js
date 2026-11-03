import { parseConfig } from './config.js';

export function createApp(raw) {
  const config = parseConfig(raw);
  return { config, url: `http://${config.host}:${config.port}`, mode: config.retries > 0 ? 'retry' : 'once' };
}
