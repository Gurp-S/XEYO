import {useTerminalSessionStore} from '@/stores/terminalSessionStore';
export function TerminalHistory() {
 const history = useTerminalSessionStore(s=>s.history);
 const setCommand = useTerminalSessionStore(s=>s.setCommand);
 return <label className="xy-call-filter">命令历史<select aria-label="终端命令历史" value="" onChange={e=>{if(e.target.value) setCommand(e.target.value);}}><option value="">{history.length ? '选择以填入命令框' : '尚无终端命令'}</option>{history.map((command,i)=><option key={i} value={command}>{command}</option>)}</select></label>;
}
