import {useEffect, useRef, useState} from 'react';

/**
 * 流式文本的自适应打字机效果。
 *
 * ≤1 次 React 更新 / 动画帧；小步揭示码点。
 * 积压过大时温和追赶（上限 6），保证末尾 N 字透明度渐变始终可见，
 * 避免一帧砸上十几二十字。
 */
export function typewriterStep(backlog: number): number {
	if (backlog <= 0) {
		return 0;
	}
	if (backlog <= 32) {
		return 1;
	}
	if (backlog <= 56) {
		return 2;
	}
	if (backlog <= 96) {
		return 3;
	}
	return Math.max(3, Math.min(6, Math.ceil(backlog / 48)));
}

/**
 * 流结束后的排水步长：基础曲线 ×3（上限 48 码点/帧），
 * 仍比直播时快，但不至于瞬间排空破坏渐变。
 */
export function drainTypewriterStep(backlog: number): number {
	return Math.min(48, Math.max(2, typewriterStep(backlog) * 3));
}

/**
 * @deprecated 保留给测试；直播路径不再使用，以免结构块突然冲字。
 */
export function structuralTypewriterStep(backlog: number): number {
	return typewriterStep(backlog);
}

/** 直播始终走平滑曲线；needsFast 忽略（API 兼容）。 */
export function streamTypewriterStepFor(
	_full: string,
	_needsFast: (text: string) => boolean,
): (backlog: number) => number {
	return typewriterStep;
}

export type TypewriterAdvanceCache = {
	full: string;
	points: string[];
	shown: string;
	index: number;
};

function isHighSurrogate(code: number): boolean {
	return code >= 0xd800 && code <= 0xdbff;
}

/**
 * 揭示前沿停在「疑似未写完的列表标号」行上时，回退到行首：
 * 等标号 + 分隔符 + 内容成形后，把「标号 + 内容首字」一次性揭示，
 * 避免 “6.嘿嘿嘿7” 这类中间态与列表项翻转引起的跳动。
 * 形状判断始终看全文中该行的完整内容：
 * - 行已是「标号 + 内容」→ 放行（跳过标号区，直接连内容一起揭示）；
 * - 行只是裸标号（流仍在继续）→ 扣住，等内容到达；
 * - 行完整且后随换行（独立的数字/短横线行）→ 放行。
 */
export function holdBackPartialListMarker(
	points: string[],
	next: number,
): number {
	if (next <= 0) {
		return next;
	}
	let lineStart = next;
	while (lineStart > 0 && points[lineStart - 1] !== '\n') {
		lineStart -= 1;
	}
	let lineEnd = next;
	while (lineEnd < points.length && points[lineEnd] !== '\n') {
		lineEnd += 1;
	}
	const lineLen = lineEnd - lineStart;
	// 标号行必然很短（如 “999. ”）；长行直接放行，也避免对超长单行做 slice/join
	if (lineLen === 0 || lineLen > 8) {
		return next;
	}
	const line = points.slice(lineStart, lineEnd).join('');
	// 「标号 + 内容」：内容已存在 → 跃过标号区，把标号和内容首字一起揭示
	if (next === lineEnd && lineEnd < points.length) {
		return next;
	}
	// 「标号 + 内容」：内容已存在 → 跃过标号区，把标号和内容首字一起揭示
	const ordered = /^(\d{1,3}[.)、][ \t]?)(\S)/.exec(line);
	const unordered = /^([-*+][ \t]?)(\S)/.exec(line);
	const match = ordered ?? unordered;
	if (match) {
		const markerLen = Array.from(match[1]).length;
		const shown = next - lineStart;
		return shown > markerLen ? next : lineStart + markerLen + 1;
	}
	// 行只是（可能未写完的）裸标号：流未结束前扣住，等内容到达
	if (/^\d{1,3}([.)、][ \t]?)?$/.test(line) || /^[-*+][ \t]?$/.test(line)) {
		return lineStart;
	}
	return next;
}

/**
 * 剩余滞后是否仅为被扣住的列表标号尾巴：
 * 直播循环的续跑条件用它豁免「扣住造成的差一口气」，避免空转；
 * 新 delta 到达时会重新调度，drain 收尾路径则直接放行。
 */
export function isOnlyHoldBackLag(text: string, shown: string): boolean {
	if (shown === text || !text.startsWith(shown)) {
		return false;
	}
	const points = Array.from(text);
	const shownLen = Array.from(shown).length;
	if (points.length - shownLen > 8) {
		return false; // 扣住窗口有限，超出即非本机制
	}
	return holdBackPartialListMarker(points, points.length) <= shownLen;
}

/**
 * 向 full 推进一轮揭示；full 换前缀时先对齐到公共码点前缀。
 * 追加式流文本复用上一帧的码点数组，只解码新增尾部；回溯或替换时
 * 才退化到完整恢复。这样不改变打字机的步进规则，但避免每帧全量 Array.from。
 */
export function advanceTypewriterShown(
	full: string,
	shown: string,
	cache?: TypewriterAdvanceCache,
	step: (backlog: number) => number = typewriterStep,
	allowHoldBack = true,
): string {
	if (!full) {
		if (cache) {
			cache.full = '';
			cache.points = [];
			cache.shown = '';
			cache.index = 0;
		}
		return '';
	}

	let points: string[];
	let cacheHit = false;
	if (cache && full === cache.full) {
		points = cache.points;
		cacheHit = true;
	} else if (cache && full.startsWith(cache.full)) {
		let prefix = cache.full;
		const hasNewCodeUnit = full.length > prefix.length;
		const trailingHigh =
			prefix.length > 0 &&
			isHighSurrogate(prefix.charCodeAt(prefix.length - 1));
		if (hasNewCodeUnit && trailingHigh) {
			prefix = prefix.slice(0, -1);
			cache.points.pop();
		}
		cache.points.push(...Array.from(full.slice(prefix.length)));
		points = cache.points;
	} else {
		points = Array.from(full);
	}

	let have = 0;
	if (full.startsWith(shown)) {
		if (cacheHit && cache?.shown === shown) {
			have = cache.index;
		} else {
			have = Array.from(shown).length;
		}
	} else {
		const prev = Array.from(shown);
		while (
			have < prev.length &&
			have < points.length &&
			prev[have] === points[have]
		) {
			have += 1;
		}
	}
	const backlog = points.length - have;
	if (backlog <= 0) {
		if (cache) {
			cache.full = full;
			cache.points = points;
			cache.shown = full;
			cache.index = points.length;
		}
		return full;
	}
	const nextRaw = Math.min(points.length, have + step(backlog));
	const next = allowHoldBack
		? holdBackPartialListMarker(points, nextRaw)
		: nextRaw;
	const result = points.slice(0, next).join('');
	if (cache) {
		cache.full = full;
		cache.points = points;
		cache.shown = result;
		cache.index = next;
	}
	return result;
}

export function useStreamTypewriter(target: string): string {
	const [shown, setShown] = useState('');
	const targetRef = useRef(target);
	const pointsRef = useRef<string[]>(Array.from(target));
	const indexRef = useRef(0);
	const shownRef = useRef('');
	// 空转修复(2026-09-05 排查·嫌疑6):旧实现 tick 末尾无条件 reschedule,
	// backlog=0 也每帧空转。改为"无进展即停",由 target 更新路径 wake 唤醒。
	const rafRef = useRef(0);
	const wakeRef = useRef<() => void>(() => {});

	useEffect(() => {
		targetRef.current = target;
		pointsRef.current = Array.from(target);
		const points = pointsRef.current;
		if (!target.startsWith(shownRef.current)) {
			let i = 0;
			const prev = Array.from(shownRef.current);
			while (
				i < prev.length &&
				i < points.length &&
				prev[i] === points[i]
			) {
				i += 1;
			}
			indexRef.current = i;
			const next = points.slice(0, i).join('');
			shownRef.current = next;
			setShown(next);
		}
		wakeRef.current();
	}, [target]);

	useEffect(() => {
		let alive = true;

		const tick = () => {
			if (!alive) {
				return;
			}
			rafRef.current = 0;
			let progress = false;
			const t = targetRef.current;
			const points = pointsRef.current;
			let i = indexRef.current;
			if (i > points.length || !t.startsWith(shownRef.current)) {
				const prev = Array.from(shownRef.current);
				i = 0;
				while (
					i < prev.length &&
					i < points.length &&
					prev[i] === points[i]
				) {
					i += 1;
				}
				const prefix = points.slice(0, i).join('');
				const changed = prefix !== shownRef.current;
				shownRef.current = prefix;
				indexRef.current = i;
				if (changed) {
					setShown(prefix);
					progress = true;
				}
			}
			const backlog = points.length - indexRef.current;
			if (backlog > 0) {
				const nextRaw = Math.min(points.length, indexRef.current + typewriterStep(backlog));
				const nextIndex = holdBackPartialListMarker(points, nextRaw);
				if (nextIndex !== indexRef.current) {
					// 回退揭示(标号行未成形)时需整体重建,而非追加
					const next = points.slice(0, nextIndex).join('');
					if (next !== shownRef.current) {
						shownRef.current = next;
						indexRef.current = nextIndex;
						setShown(next);
						progress = true;
					} else {
						indexRef.current = nextIndex;
					}
				}
			}
			// 无进展(已打完 / 标号被扣住等新 delta)即停;target 更新会 wake。
			if (
				progress ||
				indexRef.current < pointsRef.current.length ||
				!targetRef.current.startsWith(shownRef.current)
			) {
				rafRef.current = requestAnimationFrame(tick);
			}
		};

		wakeRef.current = () => {
			if (alive && rafRef.current === 0) {
				rafRef.current = requestAnimationFrame(tick);
			}
		};
		wakeRef.current();
		return () => {
			alive = false;
			wakeRef.current = () => {};
			if (rafRef.current) {
				cancelAnimationFrame(rafRef.current);
				rafRef.current = 0;
			}
		};
	}, []);

	return shown;
}
