import { formatAmount } from './money.js';

export function formatReport(ledger, options = {}) {
  if (options.json) {
    return JSON.stringify({ total: ledger.total, categories: ledger.categories, count: ledger.count }, null, 2);
  }
  const lines = [`Transactions: ${ledger.count}`, `Total: ${formatAmount(ledger.total)}`];
  for (const [category, cents] of Object.entries(ledger.categories)) {
    lines.push(`  ${category}: ${formatAmount(cents)}`);
  }
  return lines.join('\n');
}
