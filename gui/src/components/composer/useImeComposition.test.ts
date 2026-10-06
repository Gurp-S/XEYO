import {act, renderHook} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {useImeComposition} from './useImeComposition';

describe('useImeComposition', () => {
	it('组词开始就交还渲染权给 textarea', () => {
		const {result} = renderHook(() => useImeComposition());
		expect(result.current.imeRendering).toBe(false);
		act(() => result.current.onCompositionStart());
		expect(result.current.imeRendering).toBe(true);
	});

	it('compositionend 不当场交还：等下一次 value 提交（同一帧）', () => {
		const {result} = renderHook(() => useImeComposition());
		act(() => result.current.onCompositionStart());
		act(() => result.current.onCompositionEnd());
		/* 这一条就是"整行闪一下"的回归判据：旧实现此处已交还，
		   覆盖层会用还没更新到提交文本的 value 重绘。 */
		expect(result.current.imeRendering).toBe(true);

		act(() => result.current.onValueCommit());
		expect(result.current.imeRendering).toBe(false);
	});

	it('组词期间的候选更新（change）不触发交还', () => {
		const {result} = renderHook(() => useImeComposition());
		act(() => result.current.onCompositionStart());
		act(() => result.current.onValueCommit());
		act(() => result.current.onValueCommit());
		expect(result.current.imeRendering).toBe(true);
	});

	it('取消组词（引擎不发 change）由 settle 收口', () => {
		const {result} = renderHook(() => useImeComposition());
		act(() => result.current.onCompositionStart());
		act(() => result.current.onCompositionEnd());
		act(() => result.current.onSettle());
		expect(result.current.imeRendering).toBe(false);
	});

	it('非 IME 输入不受影响（无挂起时提交是空操作）', () => {
		const {result} = renderHook(() => useImeComposition());
		act(() => result.current.onValueCommit());
		expect(result.current.imeRendering).toBe(false);
		act(() => result.current.onSettle());
		expect(result.current.imeRendering).toBe(false);
	});

	it('挂起标记是一次性的：提交后不会把之后的组词状态吃掉', () => {
		const {result} = renderHook(() => useImeComposition());
		act(() => result.current.onCompositionStart());
		act(() => result.current.onCompositionEnd());
		act(() => result.current.onValueCommit());
		expect(result.current.imeRendering).toBe(false);

		/* 第二次组词：结束前仍由 textarea 渲染 */
		act(() => result.current.onCompositionStart());
		act(() => result.current.onCompositionEnd());
		expect(result.current.imeRendering).toBe(true);
		act(() => result.current.onValueCommit());
		expect(result.current.imeRendering).toBe(false);
	});
});
