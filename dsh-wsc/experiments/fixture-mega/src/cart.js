import { discountFor } from './pricing.js';

export function checkoutTotal(lines, tier) {
  const subtotal = lines.reduce((sum, line) => sum + line.priceCents * line.quantity, 0);
  return discountFor(subtotal, tier);
}
