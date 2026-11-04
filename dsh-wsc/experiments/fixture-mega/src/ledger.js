import { parseAmount } from './money.js';

export function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
  const [header, ...rows] = lines;
  const columns = header.split(',').map((name) => name.trim());
  return rows.map((row) => {
    const cells = row.split(',');
    const record = {};
    for (const [index, name] of columns.entries()) record[name] = (cells[index] ?? '').trim();
    return { date: record.date, category: record.category, amount: parseAmount(record.amount) };
  });
}

export function createLedger(transactions) {
  const total = transactions.reduce((sum, entry) => sum + entry.amount, 0);
  const categories = {};
  for (const entry of transactions) {
    categories[entry.category] = (categories[entry.category] ?? 0) + entry.amount;
  }
  return { transactions, total, categories, count: transactions.length };
}
