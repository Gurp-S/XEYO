import {useEffect, useRef, useState} from 'react';
import {useTerminalSessionStore} from '@/stores/terminalSessionStore';
import {useScrollArea} from '@/ui/useScrollArea';

const PAGE_CHARS=24_000;
export function TerminalOutput({root}: {root:string}) {
	const lines=useTerminalSessionStore(s=>s.lines);
	const discarded=useTerminalSessionStore(s=>s.discardedChars);
	const clear=useTerminalSessionStore(s=>s.clearOutput);
	// null follows the tail. Earlier pages stay put while new output arrives.
	const [offset,setOffset]=useState<number|null>(null);
	const scroller=useRef<HTMLDivElement>(null);
	const scrollArea=useScrollArea({outerRef:scroller});
	const total=lines.reduce((n,line)=>n+line.text.length+1,0);
	const tail=Math.max(0,total-PAGE_CHARS);
	const start=Math.min(offset??tail,tail);
	const end=start+PAGE_CHARS;
	let position=0;
	const visible=lines.flatMap((line,index)=>{
		const from=position;position+=line.text.length+1;
		return position>start && from<end ? [{...line,index,text:line.text.slice(Math.max(0,start-from),Math.max(0,end-from))}] : [];
	});
	useEffect(()=>{setOffset(null);},[root,discarded]);
	useEffect(()=>{if(offset===null)scroller.current?.scrollTo({top:scroller.current.scrollHeight});},[lines,offset]);
	return <>
		<div className="xy-output-controls"><span>{discarded ? `已释放较早的 ${discarded.toLocaleString()} 个字符 · ` : ''}{total ? `${start+1}–${Math.min(total,end)} / ${total} 字符` : '终端输出'}</span><button disabled={!start} onClick={()=>setOffset(Math.max(0,start-PAGE_CHARS))}>更早</button><button disabled={offset===null} onClick={()=>setOffset(start+PAGE_CHARS>=tail?null:start+PAGE_CHARS)}>更晚</button><button disabled={offset===null} onClick={()=>setOffset(null)}>最新</button><button disabled={!lines.length} onClick={clear}>清空</button></div>
		<div {...scrollArea.scrollerProps} className={scrollArea.cx('min-h-0 flex-1 overflow-auto px-3 py-2 font-mono text-[12px] leading-6 text-ink-soft')}>
			{visible.map(line=><div key={line.index} className="whitespace-pre-wrap break-words">{line.kind==='in'&&<span className="text-accent">{root?`PS ${root}> `:'❯ '}</span>}<span className={line.kind==='err'?'text-danger':line.kind==='info'?'text-mute':''}>{line.text}</span></div>)}
			{!lines.length&&<p className="text-mute">在工作区根目录执行命令。可用方向键回看命令历史。</p>}
		</div>
	</>;
}
