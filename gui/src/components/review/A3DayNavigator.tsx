/** 日列表：只认「日期 + 请求数」两样，实时账本与快照报告都能喂。 */
type DayItem = {day: string; requests?: number | null};

export function A3DayNavigator({
	days,
	selected,
	onSelect,
}: {
	days: DayItem[];
	selected: string;
	onSelect: (day: string) => void;
}) {
	return (
		<nav className="xy-a3-days" aria-label="用量日期">
			<h3>日期</h3>
			{days
				.slice()
				.reverse()
				.map(day => (
					<button
						key={day.day}
						aria-current={selected === day.day ? 'date' : undefined}
						onClick={() => onSelect(day.day)}
					>
						<strong>{day.day}</strong>
						<small>
							{day.requests == null ? '请求数未记录' : `${day.requests.toLocaleString()} 次请求`}
						</small>
					</button>
				))}
		</nav>
	);
}
