# pricing-kit

Tiered discount helper used by the checkout service.

`discountFor(subtotalCents, tier)` returns the discounted subtotal in integer cents.
Tiers: `none`, `silver`, `gold`. Discounts are 0%, 5% and 10%.
