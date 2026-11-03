export function loadSettings(raw) {
  if (raw === null || typeof raw !== 'object') throw new TypeError('settings must be an object');
  const { db } = raw;
  if (db === null || typeof db !== 'object') throw new TypeError('db must be an object');
  const { host, port } = db;
  if (typeof host !== 'string' || host.length === 0) throw new TypeError('db.host must be a non-empty string');
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RangeError('db.port must be an integer in 1..65535');
  return { database: { host, port, ssl: false } };
}
