const CODE_EXT: Record<string, string> = {
	ts: 'typescript',
	tsx: 'tsx',
	js: 'javascript',
	jsx: 'jsx',
	mjs: 'javascript',
	cjs: 'javascript',
	py: 'python',
	rs: 'rust',
	go: 'go',
	java: 'java',
	kt: 'kotlin',
	c: 'c',
	h: 'c',
	cpp: 'cpp',
	cc: 'cpp',
	hpp: 'cpp',
	cs: 'csharp',
	rb: 'ruby',
	php: 'php',
	swift: 'swift',
	sh: 'bash',
	bash: 'bash',
	zsh: 'bash',
	ps1: 'powershell',
	json: 'json',
	jsonc: 'json',
	yml: 'yaml',
	yaml: 'yaml',
	toml: 'toml',
	xml: 'xml',
	html: 'markup',
	css: 'css',
	scss: 'scss',
	less: 'less',
	sql: 'sql',
	md: 'markdown',
	mdx: 'markdown',
};

export function fileExt(name: string): string {
	const i = name.lastIndexOf('.');
	if (i <= 0 || i === name.length - 1) {
		return '';
	}
	return name.slice(i + 1).toLowerCase();
}

export function isMarkdownName(name: string): boolean {
	const ext = fileExt(name);
	return ext === 'md' || ext === 'mdx' || ext === 'markdown';
}

export function highlightLangForName(name: string): string {
	return CODE_EXT[fileExt(name)] || 'text';
}
