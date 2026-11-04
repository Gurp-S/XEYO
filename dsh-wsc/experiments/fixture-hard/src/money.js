export function parseAmount(text) {
  const value = Number.parseFloat(String(text).replace(/[^0-9.-]/g, ''));
  if (Number.isNaN(value)) throw new TypeError(`not an amount: ${text}`);
  return Math.round(value * 100);
}

export function formatAmount(cents) {
  const sign = cents < 0 ? '-' : '';
  const absolute = Math.abs(cents);
  const euros = Math.floor(absolute / 100);
  const rest = String(absolute % 100).padStart(2, '0');
  return `${sign}${euros}.${rest}`;
}
