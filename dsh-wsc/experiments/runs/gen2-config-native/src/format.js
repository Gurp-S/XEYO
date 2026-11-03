const VERSION_1_KEY = 'db';
const VERSION_2_KEY = 'database';
const KNOWN_KEYS = new Set([VERSION_1_KEY, VERSION_2_KEY]);

function requireObject(value, name) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object`);
  }
}

function requireConnection(entry, prefix) {
  const { host, port } = entry;
  if (typeof host !== 'string' || host.length === 0) throw new TypeError(`${prefix}.host must be a non-empty string`);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RangeError(`${prefix}.port must be an integer in 1..65535`);
  return { host, port };
}

function fromVersion1(db) {
  requireObject(db, VERSION_1_KEY);
  if (Object.hasOwn(db, 'ssl')) throw new TypeError('db.ssl is not expressible in version 1');
  const { host, port } = requireConnection(db, VERSION_1_KEY);
  return { database: { host, port, ssl: false } };
}

function fromVersion2(database) {
  requireObject(database, VERSION_2_KEY);
  const { host, port } = requireConnection(database, VERSION_2_KEY);
  const { ssl = false } = database;
  if (typeof ssl !== 'boolean') throw new TypeError('database.ssl must be a boolean');
  return { database: { host, port, ssl } };
}

export function normaliseSettings(raw) {
  requireObject(raw, 'settings');
  for (const key of Object.keys(raw)) {
    if (!KNOWN_KEYS.has(key)) throw new TypeError(`unknown top-level key: ${key}`);
  }
  const hasVersion1 = Object.hasOwn(raw, VERSION_1_KEY);
  const hasVersion2 = Object.hasOwn(raw, VERSION_2_KEY);
  if (hasVersion1 && hasVersion2) throw new TypeError('db and database cannot both be present');
  if (hasVersion1) return fromVersion1(raw[VERSION_1_KEY]);
  if (hasVersion2) return fromVersion2(raw[VERSION_2_KEY]);
  throw new TypeError('settings must contain db or database');
}
