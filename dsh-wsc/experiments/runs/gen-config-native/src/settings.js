const VERSION_1_KEY = 'db';
const VERSION_2_KEY = 'database';
const ALLOWED_KEYS = new Set([VERSION_1_KEY, VERSION_2_KEY]);

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export function loadSettings(raw) {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new TypeError('settings must be an object');
  }

  for (const key of Object.keys(raw)) {
    if (!ALLOWED_KEYS.has(key)) throw new TypeError(`unknown top-level key: ${key}`);
  }

  const hasVersion1 = hasOwn(raw, VERSION_1_KEY);
  const hasVersion2 = hasOwn(raw, VERSION_2_KEY);
  if (hasVersion1 && hasVersion2) {
    throw new TypeError('settings cannot contain both db and database');
  }
  if (!hasVersion1 && !hasVersion2) {
    throw new TypeError('settings must contain db or database');
  }

  return hasVersion1 ? fromVersion1(raw.db) : fromVersion2(raw.database);
}

function fromVersion1(db) {
  assertObject(db, 'db');
  if (hasOwn(db, 'ssl')) throw new TypeError('db.ssl is not supported in version 1 settings');
  const { host, port } = readHostPort(db, 'db');
  return { database: { host, port, ssl: false } };
}

function fromVersion2(database) {
  assertObject(database, 'database');
  const ssl = hasOwn(database, 'ssl') ? database.ssl : false;
  if (typeof ssl !== 'boolean') throw new TypeError('database.ssl must be a boolean');
  const { host, port } = readHostPort(database, 'database');
  return { database: { host, port, ssl } };
}

function assertObject(value, key) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${key} must be an object`);
  }
}

function readHostPort(connection, key) {
  const { host, port } = connection;
  if (typeof host !== 'string' || host.length === 0) {
    throw new TypeError(`${key}.host must be a non-empty string`);
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new RangeError(`${key}.port must be an integer in 1..65535`);
  }
  return { host, port };
}
