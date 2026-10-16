/** Resolve inside one rendered document; headings in other messages are unrelated. */
export function scrollMarkdownHeading(root: ParentNode | null, id: string): boolean {
	const heading = Array.from(root?.querySelectorAll<HTMLElement>('[id]') ?? []).find(node => node.id === id);
	heading?.scrollIntoView({block: 'start', behavior: 'smooth'});
	return Boolean(heading);
}
