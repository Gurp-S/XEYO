import {scrollMarkdownHeading} from './markdownAnchor';

/** A cold renderer may mount after the initial anchor request. */
export function followDeferredMarkdownAnchor(root: HTMLElement | null, id: string) {
	if (!root) return () => {};
	const observer = new MutationObserver(() => { if (scrollMarkdownHeading(root, id)) dispose(); });
	const timer = window.setTimeout(() => { if (scrollMarkdownHeading(root, id)) dispose(); }, 40);
	const dispose = () => { observer.disconnect(); window.clearTimeout(timer); };
	observer.observe(root, {childList: true, subtree: true});
	return dispose;
}
