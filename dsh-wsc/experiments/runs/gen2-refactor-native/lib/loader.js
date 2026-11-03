export function loadConfig(raw) {
  if (raw === null || typeof raw !== 'object') throw new TypeError('config must be an object');
  const { host, port, retries = 2 } = raw;
  if (typeof host !== 'string' || host.length === 0) throw new TypeError('host must be a non-empty string');
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new RangeError('port must be an integer in 1..65535');
  if (!Number.isInteger(retries) || retries < 0) throw new RangeError('retries must be a non-negative integer');
  return { host, port, retries };
}
