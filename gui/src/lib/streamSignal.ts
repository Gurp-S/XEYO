import {signal} from '@preact/signals-react';

/**
 * Experimental stream-only signal. The default application path never reads it.
 * Passing the signal itself to JSX lets the adapter update one text node without
 * re-running the surrounding React subtree.
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
