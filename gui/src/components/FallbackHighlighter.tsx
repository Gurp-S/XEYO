// 主线程高亮兜底(仅在 highlight worker 不可用/失败时由 CodeBlock 懒加载)。
// 独立成 chunk 的目的:react-syntax-highlighter + 28 个 refractor 语言定义
// 不进主 bundle,启动解析体积显著下降;兜底路径首次命中时才下载本模块。
import {PrismLight as SyntaxHighlighter} from 'react-syntax-highlighter';
import bash from 'refractor/bash';
import c from 'refractor/c';
import cpp from 'refractor/cpp';
import csharp from 'refractor/csharp';
import css from 'refractor/css';
import diff from 'refractor/diff';
import docker from 'refractor/docker';
import go from 'refractor/go';
import ini from 'refractor/ini';
import java from 'refractor/java';
import javascript from 'refractor/javascript';
import json from 'refractor/json';
import jsx from 'refractor/jsx';
import kotlin from 'refractor/kotlin';
import less from 'refractor/less';
import markdown from 'refractor/markdown';
import markup from 'refractor/markup';
import mermaid from 'refractor/mermaid';
import php from 'refractor/php';
import powershell from 'refractor/powershell';
import python from 'refractor/python';
import ruby from 'refractor/ruby';
import rust from 'refractor/rust';
import scss from 'refractor/scss';
import sql from 'refractor/sql';
import swift from 'refractor/swift';
import toml from 'refractor/toml';
import tsx from 'refractor/tsx';
import typescript from 'refractor/typescript';
import yaml from 'refractor/yaml';
import {
	oneDark,
	oneLight,
} from 'react-syntax-highlighter/dist/esm/styles/prism';

SyntaxHighlighter.registerLanguage('markup', markup);
SyntaxHighlighter.registerLanguage('css', css);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('jsx', jsx);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('tsx', tsx);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('rust', rust);
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('diff', diff);
SyntaxHighlighter.registerLanguage('go', go);
SyntaxHighlighter.registerLanguage('java', java);
SyntaxHighlighter.registerLanguage('c', c);
SyntaxHighlighter.registerLanguage('cpp', cpp);
SyntaxHighlighter.registerLanguage('csharp', csharp);
SyntaxHighlighter.registerLanguage('ruby', ruby);
SyntaxHighlighter.registerLanguage('kotlin', kotlin);
SyntaxHighlighter.registerLanguage('docker', docker);
SyntaxHighlighter.registerLanguage('php', php);
SyntaxHighlighter.registerLanguage('powershell', powershell);
SyntaxHighlighter.registerLanguage('toml', toml);
SyntaxHighlighter.registerLanguage('ini', ini);
SyntaxHighlighter.registerLanguage('scss', scss);
SyntaxHighlighter.registerLanguage('less', less);
SyntaxHighlighter.registerLanguage('swift', swift);
SyntaxHighlighter.registerLanguage('mermaid', mermaid);

type Props = {
	lang: string;
	dark: boolean;
	file: boolean;
	value: string;
	/** 与原 CodeBlock 内联用法逐字一致,保证兜底渲染视觉零差。 */
	customStyle: React.CSSProperties;
};

export default function FallbackHighlighter({
	lang,
	dark,
	file,
	value,
	customStyle,
}: Props) {
	return (
		<SyntaxHighlighter
			language={lang}
			style={dark ? oneDark : oneLight}
			showLineNumbers={file}
			lineNumberStyle={
				file
					? {
							minWidth: '2.75em',
							paddingRight: '1.25rem',
							color: 'var(--color-mute)',
							userSelect: 'none',
						}
					: undefined
			}
			customStyle={customStyle}
			PreTag="div"
			codeTagProps={{style: {fontFamily: 'inherit'}}}
		>
			{value || ' '}
		</SyntaxHighlighter>
	);
}
