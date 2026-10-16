import {useMemo,useState} from 'react';
import {ChevronRight} from 'lucide-react';
import {useChatStore} from '@/stores/chatStore';
import {usePanelSubtitle} from '@/lib/panelSubtitle';
import {useScrollArea} from '@/ui/useScrollArea';
import {cn} from '@/lib/utils';
import {collectCalls,callSummary} from '@/lib/toolCallHistory';
const EMPTY_COMMAND_MESSAGES: Parameters<typeof collectCalls>[0] = [];
export function ToolCallHistory() {
	const storedMessages = useChatStore(s => s.activeId ? s.messagesById[s.activeId] : undefined);
	const messages = storedMessages ?? EMPTY_COMMAND_MESSAGES;
	const commands = useMemo(() => collectCalls(messages), [messages]);
	usePanelSubtitle(`当前对话 · ${commands.length} 条`);
	const [filter, setFilter] = useState('');
 const filtered = commands.filter(c=>!filter || c.name===filter);
 const [copied, setCopied] = useState<string | null>(null);
	// 文件树式折叠：每个节点独立展开/收起（常挂载 grid-rows 平滑动画）。
	const [expanded, setExpanded] = useState<Record<string, boolean>>({});
	const area = useScrollArea({edgeFade: false});

	const onCopy = async (input: string) => {
		try {
			await navigator.clipboard.writeText(input);
			setCopied(input);
			setTimeout(() => setCopied(null), 1500);
		} catch {
			/* 忽略 */
		}
	};

	return (
		<div className="flex h-full flex-col">
   <label className="xy-call-filter">工具类型<select aria-label="筛选调用工具" value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部工具</option>{Array.from(new Set(commands.map(c=>c.name))).map(name=><option key={name}>{name}</option>)}</select></label>
			<div
				className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-1.5 py-2"
				{...area.scrollerProps}
			>
				{filtered.length === 0 ? (
					<p className="py-4 text-center text-[12px] text-mute">{filter ? '没有匹配的工具调用' : '当前对话还没有工具调用'}</p>
				) : (
					filtered.map(c => {
						const key = c.id;
						const open = Boolean(expanded[key]);
						return (
							<div key={key} className="group">
								<div className="flex items-center gap-1.5 rounded-md pr-1 text-left text-[13px] transition-colors hover:bg-glass-hover">
									<button
										type="button"
										aria-expanded={open}
										onClick={() => setExpanded(o => ({...o, [key]: !open}))}
										className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left text-ink-soft"
									>
										<span className="flex w-3.5 shrink-0 items-center justify-center text-mute">
											<ChevronRight
												className={cn(
													'h-3.5 w-3.5 transition-transform duration-150',
													open && 'rotate-90',
												)}
												strokeWidth={1.8}
											/>
										</span>
										<span className="min-w-0 flex-1 truncate">
											{callSummary(c.name,c.input,c.display)}
										</span>
									</button>
									<span className="shrink-0 rounded bg-glass-strong px-1 py-0.5 font-mono text-[10px] leading-none text-mute">
										{c.name}
									</span>
									<button
										type="button"
										className="shrink-0 rounded px-1 font-mono text-[10px] text-mute opacity-0 transition-opacity hover:text-ink group-hover:opacity-100 group-focus-within:opacity-100 xy-hover-reveal"
										title={c.name==='Bash' ? '复制命令' : '复制调用参数'}
										aria-label={c.name==='Bash' ? '复制命令' : '复制调用参数'}
										onClick={() => void onCopy(c.display)}
									>
										{copied === c.display ? '已复制' : '复制'}
									</button>
								</div>
								<div
									className={cn('xy-sidebar-tree grid', open ? 'is-open' : 'is-closed')}
									aria-hidden={!open}
								>
									<ul className="min-h-0 overflow-hidden">
									<li className="whitespace-pre-wrap break-all rounded-md px-7 py-1 text-[12px] leading-5 text-ink-soft">
										{c.display}
									</li>
									</ul>
								</div>
							</div>
						);
					})
				)}
			</div>
		</div>
	);
}
