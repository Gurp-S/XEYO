import {useState} from 'react';
import {useHeartbeat} from '@/lib/heartbeat';

function pad(n: number): string {
	return String(n).padStart(2, '0');
}

export function ImmersiveClock() {
	const [now, setNow] = useState(() => new Date());
	// 全局 1s 心跳:共享单一定时器,替代自建 setInterval(见 lib/heartbeat.ts)
	useHeartbeat(() => setNow(new Date()));
	const hh = pad(now.getHours());
	const mm = pad(now.getMinutes());
	const ss = pad(now.getSeconds());
	const date = now.toLocaleDateString('zh-CN', {
		weekday: 'long',
		month: 'long',
		day: 'numeric',
	});

	return (
		<div>
			<div className="font-mono text-6xl font-light tracking-wider text-[var(--xy-imm-fg-strong)]">
				{hh}:{mm}
				<span className="text-2xl text-[var(--xy-imm-fg-faint)]">:{ss}</span>
			</div>
			<div className="mt-2 text-[11px] tracking-[0.06em] text-[var(--xy-imm-fg-faint)]">
				{date}
			</div>
		</div>
	);
}
