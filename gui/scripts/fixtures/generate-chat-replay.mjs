import {writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const rounds = Number(process.env.XY_REPLAY_ROUNDS ?? 140);
const createdAt = 1_700_000_000_000;

function userText(i) {
	return `请离线分析第 ${i} 个模块的渲染路径，并给出不会改变现有视觉效果的优化建议。`;
}

function assistantText(i) {
	const base = [
		`这是第 ${i} 轮本地回放。当前结论是：先保持内容结构和动画边界，再减少重复的解析、布局读取与无效重绘。`,
		'',
		`- 稳定区块：历史 Markdown、已完成代码和已完成工具状态。`,
		`- 活动区块：当前回复末尾、滚动跟随和 sticky 气泡。`,
		`- 视觉约束：保留玻璃背景、渐变遮罩、侧边栏缓动与实时显示。`,
		'',
		`> 离线回放只使用本地数据，不访问模型服务，也不读取远程资源。`,
	].join('\n');
	if (i % 19 === 0) {
		return `${base}\n\n| 指标 | 当前 | 目标 |\n| --- | ---: | ---: |\n| 帧时间 | 8.2ms | 6.33ms |\n| 输入延迟 | 4.1ms | 3ms |\n| 长帧 | 30ms | 12ms |\n\n行内公式 $E=mc^2$ 与块公式：\n\n$$\n\\sum_{k=1}^{n} k = \\frac{n(n+1)}{2}\n$$`;
	}
	if (i % 13 === 0) {
		return `${base}\n\n\`\`\`typescript\nexport function keepVisualContract(value: string) {\n  return value.trimEnd();\n}\n\`\`\``;
	}
	if (i % 29 === 0) {
		return `${base}\n\n\`\`\`mermaid\ngraph TD\n  A[Input] --> B[Frame budget]\n  B --> C[Stable history]\n  C --> D[Active markdown]\n\`\`\``;
	}
	return `${base}\n\n补充说明：第 ${i} 轮用于验证长对话滚动、TurnRail、sticky 定位和历史组件引用稳定性。`;
}

function streamText() {
	const parts = [];
	for (let i = 1; i <= 55; i += 1) {
		parts.push(`### 流式段落 ${i}\n`);
		parts.push(`实时 Markdown 必须在 token 到达时继续显示，同时避免重新处理已经完成的稳定区块。第 ${i} 段包含 `);
		parts.push('性能预算、输入延迟、sticky 气泡和侧边栏动画。');
		parts.push('\n\n');
		if (i % 11 === 0) {
			parts.push('```javascript\n');
			parts.push(`const frame${i} = requestAnimationFrame(() => measure(${i}));\n`);
			parts.push('```\n\n');
		}
		if (i % 17 === 0) {
			parts.push('| 阶段 | 工作 |\n| --- | --- |\n| read | 收集几何信息 |\n| write | 写入合成属性 |\n\n');
		}
	}
	return parts.join('').repeat(3).slice(0, 30_000);
}

const messages = [];
for (let i = 1; i <= rounds; i += 1) {
	const n = String(i).padStart(4, '0');
	messages.push({
		id: `replay-user-${n}`,
		role: 'user',
		text: userText(i),
		createdAt: createdAt + i * 1000,
	});
	messages.push({
		id: `replay-assistant-${n}`,
		role: 'assistant',
		text: assistantText(i),
		createdAt: createdAt + i * 1000 + 500,
	});
}

const fixture = {
	version: 1,
	sessionId: 'xy-offline-replay',
	spaceId: 'xy-offline-space',
	scenario: 'chatpage-real-local-replay',
	messages,
	streamText: streamText(),
};

await writeFile(join(here, 'chat-replay.json'), `${JSON.stringify(fixture)}\n`, 'utf8');
console.log(JSON.stringify({rounds, messages: messages.length, streamChars: fixture.streamText.length}));
