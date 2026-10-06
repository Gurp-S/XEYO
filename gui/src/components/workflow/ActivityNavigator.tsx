import {useEffect, useMemo, useRef, useState} from 'react';
import {ChevronDown, ChevronLeft, ChevronRight, Search} from 'lucide-react';
import {activityCaption, toolCallLabel, type RoundActivity} from '@/lib/roundActivity';
import {useDismiss} from '@/ui/useDismiss';
import {ActivityIcon} from './ActivityIcon';

/** Direct navigation for long event streams, without changing their chronology. */
export function ActivityNavigator({events, activeId, onSelect}: {
	events: RoundActivity[];
	activeId: string | undefined;
	onSelect: (id: string) => void;
}) {
	const [open, setOpen] = useState(false);
	const [query, setQuery] = useState('');
	const root = useRef<HTMLDivElement>(null);
	const search = useRef<HTMLInputElement>(null);
	const index = Math.max(0, events.findIndex(event => event.id === activeId));
	// 关闭配对：Esc 归本层（escStack LIFO）+ 外点关闭。裸 document 捕获监听在
	// 流式/沉浸等层在场时会被窗口捕获先拦走——实测流式中按 Esc：回合被停、弹层不关。
	useDismiss({open, onClose: () => setOpen(false), escId: 'activity-navigator', keepOpenRefs: [root]});

	// 打开时把焦点交给搜索框，并把当前记录滚进可视区。
	useEffect(() => {
		if (!open) return;
		search.current?.focus();
		const list = root.current?.querySelector<HTMLElement>('.xy-activity-picker-list');
		const active = list?.querySelector<HTMLElement>('[aria-current="true"]');
		if (list && active) {
			list.scrollTop += active.getBoundingClientRect().top - list.getBoundingClientRect().top - (list.clientHeight - active.clientHeight) / 2;
		}
	}, [open]);
	const needle = query.trim().toLocaleLowerCase();
	const matches = useMemo(() => open ? events.map((event, ordinal) => ({event, ordinal})).filter(({event, ordinal}) =>
		!needle || `${ordinal + 1} ${activityCaption(event)} ${event.tool ? toolCallLabel(event.tool) : event.text}`.toLocaleLowerCase().includes(needle),
	) : [], [open, events, needle]);
	return <div className="xy-activity-navigator" ref={root}>
		<button aria-label="上一条记录" disabled={index === 0} onClick={() => onSelect(events[index - 1].id)}><ChevronLeft size={14}/></button>
		<button className="xy-activity-position" aria-expanded={open} aria-label="搜索并跳转活动记录" onClick={() => {setQuery(''); setOpen(value => !value);}}>{index + 1} / {events.length}<ChevronDown size={12}/></button>
		<button aria-label="下一条记录" disabled={index >= events.length - 1} onClick={() => onSelect(events[index + 1].id)}><ChevronRight size={14}/></button>
		{open && <div className="xy-activity-picker" role="dialog" aria-label="定位活动记录">
			<label><Search size={14}/><input ref={search} value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索文件、命令或记录" aria-label="搜索活动记录"/></label>
			<div className="xy-activity-picker-list">
				{matches.map(({event, ordinal}) => <button key={event.id} aria-current={event.id === activeId ? 'true' : undefined} title={event.tool ? toolCallLabel(event.tool) : event.label} onClick={() => {onSelect(event.id); setOpen(false);}}>
					<small>{ordinal + 1}</small><ActivityIcon event={event}/><span>{activityCaption(event)}</span>{event.error && <i className="xy-activity-error-dot" aria-label="失败"/>}
				</button>)}
				{!matches.length && <p>没有匹配的记录</p>}
			</div>
		</div>}
	</div>;
}
