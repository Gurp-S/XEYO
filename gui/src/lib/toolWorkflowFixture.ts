/**
 * 整轮工具流程展示用的「热闹」fixture。
 * 供 vitest / preview:workflow 共用，覆盖 Thought、旁白、多类工具、diff、结论。
 */

import type {TurnItem, ToolView} from './groupTranscript';
import type {ChatMessage} from './types';

export const WORKFLOW_T0 = Date.UTC(2026, 7, 28, 10, 0, 0);

export function workflowMsg(
	partial: Partial<ChatMessage> & Pick<ChatMessage, 'id' | 'role' | 'text'>,
): ChatMessage {
	return {
		createdAt: WORKFLOW_T0,
		...partial,
	};
}

export function workflowTool(
	partial: Omit<ToolView, 'createdAt'> & {createdAt?: number},
): ToolView {
	return {
		createdAt: WORKFLOW_T0,
		...partial,
	};
}

export type WorkflowFixtureMode = 'live' | 'settled';

/**
 * 构造尽量完整的一轮 transcript：
 * Thought → 旁白 → Grep → 旁白 → Read/Glob/Read → 旁白 → Grep → Edit → Bash
 * settled 时再追加最终结论；live 时末尾挂一个 running Read。
 */
export function buildToolWorkflowFixture(
	mode: WorkflowFixtureMode = 'settled',
): TurnItem[] {
	const live = mode === 'live';
	const t0 = WORKFLOW_T0;
	const items: TurnItem[] = [];

	items.push({
		kind: 'assistant',
		message: workflowMsg({
			id: 'thought-1',
			role: 'assistant',
			text: '先确认 TitleBar 里最小化/最大化图标从哪来，再搜 lucide 引用。',
			isThought: true,
			thoughtMs: 6200,
			createdAt: t0,
		}),
	});

	items.push({
		kind: 'assistant',
		message: workflowMsg({
			id: 'narration-1',
			role: 'assistant',
			text: '我来帮你找到XEYO项目中最小化和最大化按钮的图标位置。让我先搜索相关的代码文件...',
			createdAt: t0 + 100,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'grep-1',
			name: 'Grep',
			input: JSON.stringify({
				pattern: 'maximize|minimize|SquareStack',
				path: 'gui',
			}),
			result: 'gui/src/components/TitleBar.tsx\n  187: SquareStack',
			status: 'done',
			createdAt: t0 + 200,
			reasoningBefore: '需要定位窗口控制按钮',
			thoughtMs: 3000,
		}),
	});

	items.push({
		kind: 'assistant',
		message: workflowMsg({
			id: 'narration-2',
			role: 'assistant',
			text: '现在让我查看 TitleBar.tsx 的具体实现：',
			createdAt: t0 + 300,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'read-1',
			name: 'Read',
			input: JSON.stringify({
				file_path: 'gui/src/components/TitleBar.tsx',
				offset: 160,
				limit: 40,
			}),
			result:
				"import {Minus, Square, SquareStack, Moon} from 'lucide-react'\n" +
				'// maximize button uses SquareStack when restored\n',
			status: 'done',
			createdAt: t0 + 400,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'glob-1',
			name: 'Glob',
			input: JSON.stringify({pattern: '**/TitleBar*.tsx'}),
			result: 'Found 1 file\ngui/src/components/TitleBar.tsx',
			status: 'done',
			createdAt: t0 + 500,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'read-2',
			name: 'Read',
			input: JSON.stringify({file_path: 'gui/package.json'}),
			result: '{"dependencies":{"lucide-react":"^0.511.0"}}',
			status: 'done',
			createdAt: t0 + 600,
		}),
	});

	items.push({
		kind: 'assistant',
		message: workflowMsg({
			id: 'narration-3',
			role: 'assistant',
			text: '让我再搜一下项目里还有没有别的窗口按钮实现：',
			createdAt: t0 + 700,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'grep-2',
			name: 'Grep',
			input: JSON.stringify({
				pattern: 'startDragging|getCurrentWindow',
				glob: '**/*.{ts,tsx}',
			}),
			result:
				'gui/src/components/TitleBar.tsx\ngui/src/pet/PetBridge.ts',
			status: 'done',
			createdAt: t0 + 800,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'write-1',
			name: 'Write',
			input: JSON.stringify({
				file_path: 'gui/src/lib/processNarration.ts',
				content: 'export function isProcessNarration() {}',
			}),
			result: 'Wrote gui/src/lib/processNarration.ts\n+++ created',
			status: 'done',
			createdAt: t0 + 850,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'edit-1',
			name: 'Edit',
			input: JSON.stringify({
				file_path: 'gui/src/components/TitleBar.tsx',
				old_string: 'import {Minus, Square,',
				new_string: 'import {Minus, Square, SquareStack,',
			}),
			result: [
				'<<<<<<< SEARCH',
				'=======',
				'>>>>>>> REPLACE',
				'@@',
				'-import {Minus, Square,',
				'+import {Minus, Square, SquareStack,',
				'+++ a/gui/src/components/TitleBar.tsx',
				'+3 -1',
			].join('\n'),
			status: 'done',
			createdAt: t0 + 900,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'todo-1',
			name: 'TodoWrite',
			input: JSON.stringify({
				todos: [
					{id: '1', content: '定位图标', status: 'completed'},
					{id: '2', content: '补 SquareStack import', status: 'in_progress'},
				],
			}),
			result: 'Updated todos',
			status: 'done',
			createdAt: t0 + 950,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'bash-1',
			name: 'Bash',
			input: JSON.stringify({
				command:
					'cd gui && npx vitest run src/lib/toolWorkflowDisplay.test.ts',
			}),
			result: 'Test Files  1 passed (1)\nTests  12 passed',
			status: 'done',
			createdAt: t0 + 1000,
		}),
	});

	items.push({
		kind: 'tool',
		tool: workflowTool({
			id: 'fail-1',
			name: 'Bash',
			input: JSON.stringify({command: 'cd gui && npx tsc -b --pretty false'}),
			result: 'error TS2304: Cannot find name SquareStack',
			status: 'error',
			createdAt: t0 + 1050,
		}),
	});

	if (live) {
		items.push({
			kind: 'tool',
			tool: workflowTool({
				id: 'read-live',
				name: 'Read',
				input: JSON.stringify({
					file_path: 'gui/src/components/ActivityLog.tsx',
				}),
				result: '',
				status: 'running',
				createdAt: t0 + 1100,
			}),
		});
	} else {
		items.push({
			kind: 'assistant',
			message: workflowMsg({
				id: 'final-1',
				role: 'assistant',
				text: [
					'根据代码分析，我找到了XEYO项目中最小化和最大化按钮的图标位置：',
					'',
					'## 最小化按钮',
					'- 文件位置: `gui/src/components/TitleBar.tsx`',
					'- 代码行数: 第167-177行',
					'- 图标组件: `<Minus>`（lucide-react）',
					'',
					'## 最大化按钮',
					'- 图标组件: `<Square>` / `<SquareStack>`（lucide-react）',
				].join('\n'),
				createdAt: t0 + 1200,
			}),
		});
	}

	return items;
}

/** 多轮 submit：两轮 turn，供 mergeTurnActivity / done on 测试 */
export function buildMultiTurnWorkflowFixture(): TurnItem[][] {
	const t0 = WORKFLOW_T0;
	const turn1 = buildToolWorkflowFixture('settled').filter(
		item =>
			!(
				item.kind === 'assistant' &&
				item.message.id === 'final-1'
			),
	);
	const turn2: TurnItem[] = [
		{
			kind: 'assistant',
			message: workflowMsg({
				id: 'narration-t2',
				role: 'assistant',
				text: '让我再核对一下最大化图标在还原态是否用 SquareStack：',
				createdAt: t0 + 2000,
			}),
		},
		{
			kind: 'tool',
			tool: workflowTool({
				id: 'read-t2',
				name: 'Read',
				input: JSON.stringify({
					file_path: 'gui/src/components/TitleBar.tsx',
					offset: 180,
					limit: 20,
				}),
				result: 'maximized ? <Square /> : <SquareStack />',
				status: 'done',
				createdAt: t0 + 2100,
			}),
		},
		{
			kind: 'assistant',
			message: workflowMsg({
				id: 'final-t2',
				role: 'assistant',
				text: '确认：还原窗口时用 `SquareStack`，最大化后用 `Square`。',
				createdAt: t0 + 2200,
			}),
		},
	];
	return [turn1, turn2];
}
