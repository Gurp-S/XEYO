import {useEffect, useState} from 'react';

function pad(n: number): string {
	return String(n).padStart(2, '0');
}

export function ImmersiveClock() {
	const [now, setNow] = useState(() => new Date());
	useEffect(() => {
		const id = setInterval(() => setNow(new Date()), 1000);
		return () => clearInterval(id);
	}, []);
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
			<div className="font-mono text-6xl font-light tracking-wider text-white/95">
				{hh}:{mm}
				<span className="text-2xl text-white/55">:{ss}</span>
			</div>
			<div className="mt-2 font-mono text-[11px] tracking-[0.2em] text-white/45">
				{date}
			</div>
		</div>
	);
}
