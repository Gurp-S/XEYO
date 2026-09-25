export type FileReferenceQueryResult = {key: string; files: string[]};

export function fileReferenceQueryKey(
	workspace: string,
	query: string,
): string | null {
	const root = workspace.trim();
	return root ? JSON.stringify([root, query.trim()]) : null;
}

export function currentFileReferenceResult(
	result: FileReferenceQueryResult | null,
	key: string | null,
): FileReferenceQueryResult | null {
	return key && result?.key === key ? result : null;
}
