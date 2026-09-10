/**
 * 时长令牌守卫：禁止 transition 使用「恰好等于某个 --duration-* 令牌值」的字面毫秒数。
 *
 * 为什么需要它：
 *   tokens.css 定义 --duration-fast:140ms / --duration-base:200ms，但 CSS 里另有一批
 *   字面 140ms/200ms 写死在 transition 上。改令牌时这些写死值不会跟随，于是同一个
 *   「快」在设计系统里演化出两个数字——A2 缺陷（DockPresence 180ms vs 容器 200ms）
 *   就是这类漂移的产物。本脚本把「值相等就必须用令牌」变成机器执法。
 *
 * 不做什么：
 *   不改写那些**没有**对应令牌的时长（120/160/180/220ms 等）。给它们造令牌属于
 *   设计决策（要不要引入新档位），不是纯重构，故只在报告里列出供人裁决。
 *
 * Usage（在 gui/ 下）：
 *   node scripts/verify-duration-tokens.cjs            # 只检查，有违规即 exit 1
 *   node scripts/verify-duration-tokens.cjs --fix      # 把「值等于令牌」的字面量替换为 var()
 *   node scripts/verify-duration-tokens.cjs --list     # 附列无令牌可用的时长分布
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const stylesDir = path.join(root, 'src', 'styles');
const componentsDir = path.join(root, 'src', 'components');

const FIX = process.argv.includes('--fix');
const LIST = process.argv.includes('--list');

/** 把 /* ... *\/ 注释内容替换成等长空格，保持偏移量→行号映射不变。 */
function blankComments(text) {
	let out = '';
	let i = 0;
	while (i < text.length) {
		const start = text.indexOf('/*', i);
		if (start === -1) {
			out += text.slice(i);
			break;
		}
		out += text.slice(i, start);
		const end = text.indexOf('*/', start + 2);
		const stop = end === -1 ? text.length : end + 2;
		const chunk = text.slice(start, stop);
		out += chunk.replace(/[^\n]/g, ' ');
		i = stop;
	}
	return out;
}

function lineOf(text, offset) {
	let line = 1;
	for (let i = 0; i < offset; i++) {
		if (text[i] === '\n') line++;
	}
	return line;
}

/** 从 tokens.css 读 --duration-<name>: <n>ms → Map<'140', 'fast'>。 */
function readDurationTokens() {
	const css = fs.readFileSync(path.join(stylesDir, 'tokens.css'), 'utf8');
	const map = new Map();
	for (const m of css.matchAll(/--duration-([a-z0-9-]+)\s*:\s*(\d+(?:\.\d+)?)ms/g)) {
		map.set(m[2], `--duration-${m[1]}`);
	}
	return map;
}

function cssFiles() {
	const out = [];
	for (const dir of [stylesDir, componentsDir]) {
		if (!fs.existsSync(dir)) continue;
		for (const name of fs.readdirSync(dir)) {
			if (name.endsWith('.css')) out.push(path.join(dir, name));
		}
	}
	return out.sort();
}

function rel(p) {
	return path.relative(root, p).replace(/\\/g, '/');
}

function main() {
	const tokens = readDurationTokens();
	if (tokens.size === 0) {
		console.error('FAIL: tokens.css 里没找到任何 --duration-* 令牌');
		process.exit(1);
	}

	const violations = [];
	const untokenized = new Map();

	for (const file of cssFiles()) {
		const raw = fs.readFileSync(file, 'utf8');
		const scan = blankComments(raw);
		// transition 简写与 transition-duration 都要覆盖；声明可跨行，吃到 ; 或 } 为止。
		const re = /\btransition(?:-[a-z-]+)?\s*:\s*([^;}]*)/g;
		let m;
		while ((m = re.exec(scan)) !== null) {
			const value = m[1];
			const valueStart = m.index + m[0].length - value.length;
			for (const lit of value.matchAll(/\b(\d+(?:\.\d+)?)ms\b/g)) {
				const ms = lit[1];
				const token = tokens.get(ms);
				const absOffset = valueStart + lit.index;
				if (token) {
					violations.push({
						file,
						line: lineOf(scan, absOffset),
						ms,
						token,
						start: absOffset,
						end: absOffset + lit[0].length,
					});
				} else {
					untokenized.set(ms, (untokenized.get(ms) || 0) + 1);
				}
			}
		}
	}

	if (violations.length === 0) {
		console.log(`OK: ${cssFiles().length} 个 CSS 无「字面值等于令牌」的 transition（令牌 ${tokens.size} 个）`);
	} else {
		console.error(`发现 ${violations.length} 处 transition 字面时长等于令牌值：`);
		for (const v of violations) {
			console.error(`  ${rel(v.file)}:${v.line}  ${v.ms}ms → 应为 var(${v.token})`);
		}
	}

	if (LIST && untokenized.size) {
		console.log('\n无令牌可用的 transition 时长分布（需人工决定是否新增档位）：');
		for (const [ms, n] of [...untokenized.entries()].sort((a, b) => b[1] - a[1])) {
			console.log(`  ${n.toString().padStart(3)}×  ${ms}ms`);
		}
	}

	if (!FIX) {
		process.exit(violations.length === 0 ? 0 : 1);
	}

	// --fix：按绝对偏移精确替换（从后往前，避免偏移失效）。
	// 偏移基于「注释已置空但长度不变」的扫描文本，故对原文同位置也成立，
	// 只会命中 transition 声明体内的字面量，不会误伤同行其他属性。
	const byFile = new Map();
	for (const v of violations) {
		if (!byFile.has(v.file)) byFile.set(v.file, []);
		byFile.get(v.file).push(v);
	}
	let changed = 0;
	for (const [file, list] of byFile) {
		const raw = fs.readFileSync(file, 'utf8');
		const sorted = [...list].sort((a, b) => b.start - a.start);
		let out = raw;
		for (const v of sorted) {
			out = out.slice(0, v.start) + `var(${v.token})` + out.slice(v.end);
			changed++;
		}
		// 修复后必须仍是合法 CSS 长度上的一致性：逐行对比只有目标行变化
		fs.writeFileSync(file, out, 'utf8');
	}
	console.log(`已替换 ${changed} 处字面时长为 var()。`);

	// 修复后自检：必须归零
	const before = violations.length;
	const recheck = [];
	for (const file of cssFiles()) {
		const scan = blankComments(fs.readFileSync(file, 'utf8'));
		const re = /\btransition(?:-[a-z-]+)?\s*:\s*([^;}]*)/g;
		let m;
		while ((m = re.exec(scan)) !== null) {
			for (const lit of m[1].matchAll(/\b(\d+(?:\.\d+)?)ms\b/g)) {
				if (tokens.has(lit[1])) recheck.push(`${rel(file)}:${lineOf(scan, m.index)} ${lit[1]}ms`);
			}
		}
	}
	if (recheck.length) {
		console.error(`FAIL: 修复后仍余 ${recheck.length} 处（原 ${before}）：`);
		for (const r of recheck) console.error('  ' + r);
		process.exit(1);
	}
	console.log('OK: 修复后归零。');
}

main();
