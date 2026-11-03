const VERSION_1_KEY = 'db';
const VERSION_2_KEY = 'database';

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function readHost(section, key) {
  const { host } = section;
  if (typeof host !== 'string' || host.length === 0) throw new TypeError(`${key}.host must be a non-empty string`);
  return host;
}

function readPort(section, key) {
  const { port } = section;
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RangeError(`${key}.port must be an integer in 1..65535`);
  return port;
}

function normaliseVersion1(section) {
  if (!isPlainObject(section)) throw new TypeError('db must be an object');
  if (Object.hasOwn(section, 'ssl')) throw new TypeError('db.ssl is not supported by version 1 settings');
  const host = readHost(section, VERSION_1_KEY);
  const port = readPort(section, VERSION_1_KEY);
  return { host, port, ssl: false };
}

function normaliseVersion2(section) {
  if (!isPlainObject(section)) throw new TypeError('database must be an object');
  const host = readHost(section, VERSION_2_KEY);
  const port = readPort(section, VERSION_2_KEY);
  const { ssl = false } = section;
  if (typeof ssl !== 'boolean') throw new TypeError('database.ssl must be a boolean');
  return { host, port, ssl };
}

export function loadSettings(raw) {
  if (raw === null || typeof raw !== 'object') throw new TypeError('settings must be an object');

  for (const key of Object.keys(raw)) {
    if (key !== VERSION_1_KEY && key !== VERSION_2_KEY) throw new TypeError(`unknown top-level key: ${key}`);
  }

  const hasVersion1 = Object.hasOwn(raw, VERSION_1_KEY);
  const hasVersion2 = Object.hasOwn(raw, VERSION_2_KEY);
  if (hasVersion1 && hasVersion2) throw new TypeError('settings must not carry both db and database');

  const database = hasVersion2 ? normaliseVersion2(raw.database) : normaliseVersion1(raw.db);
  return { database };
}
