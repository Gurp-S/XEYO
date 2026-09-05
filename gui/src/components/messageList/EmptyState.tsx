/**
 * Empty transcript state, extracted from MessageList.tsx (presentational only).
 */
export function EmptyState({
	workspaceName,
	emptyQuip,
}: {
	workspaceName: string;
	emptyQuip: string;
}) {
	return (
		<div className="relative min-h-0 min-w-0 flex-1">
			<div className="anim-rise px-6 pt-4 sm:px-8 sm:pt-6 md:px-10">
				<p className="max-w-2xl text-left font-sans text-2xl font-medium tracking-tight text-ink sm:text-3xl">
					在「{workspaceName}」里，我们要一起构建些什么呢？
				</p>
				<p
					data-testid="empty-quip"
					className="mt-2.5 max-w-xl text-left font-sans text-sm leading-relaxed text-mute sm:text-[15px]"
				>
					{emptyQuip}
				</p>
			</div>
		</div>
	);
}
