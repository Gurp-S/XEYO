const fs = require('fs');
const path = require('path');

// usage: node _orphan_scan.js <root>
const root = process.argv[2];

function* walk(d) {
  for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, ent.name);
    if (ent.isDirectory()) yield* walk(fp);
    else if (ent.name.endsWith('.ts') || ent.name.endsWith('.tsx')) yield fp;
  }
}

const files = [...walk(root)].map(f => f.replace(/\\/g, '/'));
const contents = new Map();
for (const f of files) {
  try { contents.set(f, fs.readFileSync(f, 'utf8')); } catch { }
}

const isTest = f => /\.test\.(ts|tsx)$|\.spec\.(ts|tsx)$/i.test(f) || /\/__tests__\//.test(f);

// 只看 components/ 与 stores/ 下的非测试导出文件
const targets = files.filter(f =>
  !isTest(f) &&
  (f.includes('/components/') || f.includes('/stores/') || f.includes('/lib/') || f.includes('/hooks/') || f.includes('/paths/')) &&
  !f.endsWith('.d.ts')
);

const rows = [];
for (const t of targets) {
  const base = path.basename(t).replace(/\.tsx?$/, '');
  if (/^(index)$/.test(base)) continue;
  // 引用者 = 其余文件(排除自身与该文件的 test 变体) 内容包含 \bBase\b
  const selfTest = t.replace(/\.(ts|tsx)$/, '.test.$1');
  let users = [];
  for (const f of files) {
    if (f === t || f === selfTest) continue;
    const c = contents.get(f) || '';
    const re = new RegExp(`['"]@/.*/${base}['"]|['"]\\.\\.?/.*${base}['"]|['"][^'"]*${base}.tsx?['"]`, 'm');
    // 更宽松：任何引用该基名的 import 字符串
    const re2 = new RegExp(`(import|from|require\\(|lazy\\(|component:|element:)\\s*[('"\\s]*[^'"\\n]*${base}`, 'm');
    if (re2.test(c)) users.push(f);
  }
  if (users.length === 0) {
    rows.push({ file: t, users: [] });
  }
}

console.log('=== 零引用(非测试)候选: ' + rows.length + ' ===');
for (const r of rows) console.log(r.file);
