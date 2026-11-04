const RATES = { none: 0, silver: 0.05, gold: 0.1 };

// v2: discount table normalised, tiers read from one place.
export function discountFor(subtotalCents, tier) {
  const rate = RATES[tier];
  if (rate === undefined) throw new TypeError(`unknown tier: ${tier}`);
  const discount = subtotalCents * rate;
  return subtotalCents - Math.floor(discount);
}
