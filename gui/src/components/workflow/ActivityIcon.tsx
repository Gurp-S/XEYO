import {Brain, FileText, FilePenLine, Search, Terminal, ListTodo, Wrench, MessageSquare, GitBranch} from 'lucide-react';
import type {RoundActivity} from '@/lib/roundActivity';
import {categorize} from '@/lib/toolActivity';

export function ActivityIcon({event}: {event: RoundActivity}) {
 const cat = event.tool ? categorize(event.tool.name) : '';
 const Icon = event.label === '思考' ? Brain : event.label === '回复' ? MessageSquare :
  cat === 'read' ? FileText : cat === 'edit' || cat === 'write' ? FilePenLine :
  cat === 'search' ? Search : cat === 'run' || cat === 'lint' ? Terminal :
  cat === 'todo' ? ListTodo : event.tool?.name.toLowerCase().includes('agent') ? GitBranch : Wrench;
 return <Icon size={13} aria-hidden />;
}
