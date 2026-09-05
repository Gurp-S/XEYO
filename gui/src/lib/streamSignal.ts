import {signal} from '@preact/signals-react';

/**
 * 实验性的 stream 专用 signal。默认应用路径不会读取它。
 * 将 signal 本体传入 JSX，可让适配器只更新一个文本节点，
 * 而无需重跑周围的 React 子树。
 */
export const streamingTextSignal = signal('');
export const streamingSignalEligible = signal(false);

export const streamSignalsEnabled = import.meta.env.VITE_XY_STREAM_SIGNALS === '1';

function hasMarkdownSyntax(value: string): boolean {
	return /(^|\n)\s{0,3}(?:#{1,6}\s|[-*+]\s|>\s|```|~~~|\|)/.test(value) ||
		/[`*_~[\]$<>]/.test(value);
}

export function setStreamingTextSignal(value: string): void {
	if (!value) {
		if (streamingTextSignal.value !== '') {
			streamingTextSignal.value = '';
		}
		if (streamingSignalEligible.value) {
			streamingSignalEligible.value = false;
		}
		return;
	}
	if (streamingSignalEligible.value && hasMarkdownSyntax(value)) {
		streamingSignalEligible.value = false;
	}
	if (!streamingSignalEligible.value && !hasMarkdownSyntax(value)) {
		streamingSignalEligible.value = true;
	}
	if (streamingTextSignal.value !== value) {
		streamingTextSignal.value = value;
	}
}
