const V1_KEY = 'db';
const V2_KEY = 'database';
const KNOWN_KEYS = new Set([V1_KEY, V2_KEY]);

export function loadSettings(raw) {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new TypeError('settings must be an object');
  }

  for (const key of Object.keys(raw)) {
    if (!KNOWN_KEYS.has(key)) throw new TypeError(`unknown top-level key: ${key}`);
  }

  const hasV1 = Object.hasOwn(raw, V1_KEY);
  const hasV2 = Object.hasOwn(raw, V2_KEY);
  if (hasV1 && hasV2) throw new TypeError('settings must not carry both db and database');
  if (!hasV1 && !hasV2) throw new TypeError('settings must carry either db or database');

  return hasV1 ? normaliseVersion1(raw[V1_KEY]) : normaliseVersion2(raw[V2_KEY]);
}

function normaliseVersion1(db) {
  assertObject(db, V1_KEY);
  // Version 1 has no way to express `ssl`; silently accepting it would invent intent.
  if (Object.hasOwn(db, 'ssl')) {
    throw new TypeError('db.ssl is not supported in version 1; express it as database.ssl');
  }
  return { database: { ...readConnection(db, V1_KEY), ssl: false } };
}

function normaliseVersion2(database) {
  assertObject(database, V2_KEY);
  const { ssl = false } = database;
  if (typeof ssl !== 'boolean') throw new TypeError('database.ssl must be a boolean');
  return { database: { ...readConnection(database, V2_KEY), ssl } };
}

function assertObject(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
}

function readConnection(config, label) {
  const { host, port } = config;
  if (typeof host !== 'string' || host.length === 0) throw new TypeError(`${label}.host must be a non-empty string`);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RangeError(`${label}.port must be an integer in 1..65535`);
  return { host, port };
}
