import remend, {isWithinCodeBlock, type RemendOptions} from 'remend';

/**
 * 增量 remend：长文流式时避免每帧对全文跑 remend 的 O(n) 配对扫描。
 *
 * remend 各 handler 的「修改」都只落在文本尾部（收尾未闭合构造）；
 * 在「``` 围栏（行首与任意位置两种语义）、$$、未闭合单反引号均闭合的空行」
 * 处切分后，对尾部单独 remend 与全文 remend 等价——所有配对计数在切分点前
 * 的奇偶为偶，尾部自身扫描即可得到与全文一致的全局奇偶。
 *
 * 两个全局转义规则（singleTilde / comparisonOperators）会改写正文中段，
 * 单独在全文上预应用；它们有 includes 快速路径，不含目标字符时零开销。
 *
 * 已知偏差（相对全量 remend）：若正文更早处本身留有未闭合的星号/波浪号等
 * 行内配对（跨过空行仍未闭合），全量版会把收尾追加到文本最末（中间整段
 * 被渲染成该样式），增量版保持前文原样。此类内容本身属于病态输入。
 */

const TILDE_RE = /([\p{L}\p{N}_])~(?!~)(?=[\p{L}\p{N}_])/gu;
const COMPARISON_RE = /^(\s*(?:[-*+]|\d+[.)]) +)>(=?\s*[$]?\d)/gm;

/**
 * 全文预应用两个全局转义规则（与 remend 内部实现逐字一致）。
 * 返回转义后的文本与「转义插入导致边界偏移后的新边界」。
 */
function applyGlobalEscapes(
	raw: string,
	boundary: number,
): {text: string; boundary: number} {
	let shift = 0;
	let out = raw;
	if (out.includes('~')) {
		out = out.replace(TILDE_RE, (match, before: string, offset: number) => {
			// 代码块/代码跨度内不转义（remend 同款判断）
			if (isWithinCodeBlock(out, offset + before.length)) {
				return match;
			}
			if (offset < boundary) {
				shift += 1;
			}
			return `${before}\\~`;
		});
	}
	if (out.includes('>')) {
		out = out.replace(
			COMPARISON_RE,
			(match, head: string, rest: string, offset: number) => {
				if (isWithinCodeBlock(out, offset)) {
					return match;
				}
				if (offset < boundary) {
					shift += 1;
				}
				return `${head}\\>${rest}`;
			},
		);
	}
	return {text: out, boundary: boundary + shift};
}

type ScanState = {
	scanned: number;
	/** kn 语义：任意 ``` 配对奇偶（转义感知，含行内）。 */
	knFenceOpen: boolean;
	/** ^``` 行首围栏计数奇偶（partialFenceCloser 语义）。 */
	lineFenceOdd: boolean;
	/** Gn 语义：单反引号开合态。 */
	gnTick: boolean;
	/** Gn 语义：$$ 配对奇偶。 */
	gnMathOdd: boolean;
	/** 当前行的起始偏移。 */
	lineStart: number;
	/** 最近一个安全边界（空行后的下一行行首）。 */
	lastSafe: number;
};

function freshScanState(): ScanState {
	return {
		scanned: 0,
		knFenceOpen: false,
		lineFenceOdd: false,
		gnTick: false,
		gnMathOdd: false,
		lineStart: 0,
		lastSafe: 0,
	};
}

/** sn：remend 内部判断位置是否落在 ``` 三连内。 */
function isPartOfTriple(text: string, i: number): boolean {
	return (
		(i >= 2 && text.slice(i - 2, i + 1) === '```') ||
		(i >= 1 && text.slice(i - 1, i + 2) === '```') ||
		(i <= text.length - 3 && text.slice(i, i + 3) === '```')
	);
}

function isBlankLine(line: string): boolean {
	return /^\s*$/.test(line);
}

/** 从 state.scanned 起扫描新增文本，维护配对奇偶与最近安全边界。 */
function scanDelta(state: ScanState, text: string): void {
	const len = text.length;
	let i = state.scanned;
	while (i < len) {
		const ch = text[i];
		// kn 的 \` 转义
		if (ch === '\\' && text[i + 1] === '`') {
			i += 2;
			continue;
		}
		// 行首 ``` 围栏（partialFenceCloser 语义）
		if (i === state.lineStart && text.slice(i, i + 3) === '```') {
			state.lineFenceOdd = !state.lineFenceOdd;
		}
		// kn：任意 ``` 翻转围栏态
		if (text.slice(i, i + 3) === '```') {
			state.knFenceOpen = !state.knFenceOpen;
			i += 3;
			continue;
		}
		// Gn：单反引号开合（三连内的反引号不计）
		if (ch === '`' && !isPartOfTriple(text, i)) {
			state.gnTick = !state.gnTick;
		}
		// Gn：$$ 配对（仅在单反引号闭合态计数）
		if (!state.gnTick && ch === '$' && text[i + 1] === '$') {
			state.gnMathOdd = !state.gnMathOdd;
			i += 2;
			continue;
		}
		if (ch === '\n') {
			const line = text.slice(state.lineStart, i);
			if (
				isBlankLine(line) &&
				!state.knFenceOpen &&
				!state.lineFenceOdd &&
				!state.gnMathOdd &&
				!state.gnTick
			) {
				state.lastSafe = i + 1;
			}
			state.lineStart = i + 1;
		}
		i += 1;
	}
	state.scanned = len;
}

/**
 * 创建增量 remend 实例。文本必须整体替换传入（打字机追加式推进时
 * 只扫增量、只 remend 尾部）；内容回溯/替换时自动全量重扫回退。
 */
export function createIncrementalRemend(
	options: RemendOptions,
): (text: string) => string {
	const tailOptions: RemendOptions = {
		...options,
		singleTilde: false,
		comparisonOperators: false,
	};
	let cacheRaw = '';
	let cacheOutput = '';
	let state = freshScanState();

	return function incrementalRemend(text: string): string {
		if (text === cacheRaw) {
			return cacheOutput;
		}
		try {
			if (!text.startsWith(cacheRaw)) {
				state = freshScanState();
			}
			scanDelta(state, text);
			const {text: escaped, boundary} = applyGlobalEscapes(text, state.lastSafe);
			cacheRaw = text;
			cacheOutput =
				boundary > 0
					? escaped.slice(0, boundary) +
						remend(escaped.slice(boundary), tailOptions)
					: remend(escaped, tailOptions);
			return cacheOutput;
		} catch {
			// 任何异常都回退到全量 remend，保证渲染正确性
			cacheRaw = text;
			cacheOutput = remend(text, options);
			state = freshScanState();
			return cacheOutput;
		}
	};
}
