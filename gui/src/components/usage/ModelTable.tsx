import type {ReactNode} from 'react';
import type {LiveUsageModelRow} from '@/lib/api/liveUsage';
import {cn} from '@/lib/utils';
import {NO_DATA, compactToken, costLabel, intLabel, rateLabel, shortModel, tokenLabel} from './labels';

/**
 * 分模型表：命中率与请求数各带一根条（网页报告的「分模型对比」+「分模型」两张表合成一张）。
 *
 * 条长按**当天**的最大请求数归一（不是全局），所以切日时条长会跟着变——这是"这一天谁跑得多"
 * 的相对读数，不是跨日趋势；跨日趋势看热力图与历史表。颜色由调用方按模型顺序给
 * （环形卡与这张表同一份映射，否则同一个模型在两处两种颜色）。
 */
export function ModelTable({
	rows,
	colorOf,
}: {
	rows: LiveUsageModelRow[];
	colorOf: (model: string) => string;
}) {
	if (rows.length === 0) {
		return <p className="px-4 py-3 text-[12px] text-mute">这一天没有分模型行。</p>;
	}
	const maxReq = Math.max(1, ...rows.map(r => r.requests ?? 0));
	return (
		<div className="overflow-x-auto px-4 py-3" data-a3-models>
			<table className="w-full border-collapse text-[12px]">
				<thead>
					<tr className="border-y border-line bg-paper-deep">
						<Th>模型</Th>
						<Th>渠道</Th>
						<Th num>命中率</Th>
						<Th num>命中/输入</Th>
						<Th num>请求</Th>
						<Th num>输出</Th>
						<Th num>成本</Th>
					</tr>
				</thead>
				<tbody>
					{rows.map((m, i) => {
						const color = colorOf(m.model ?? '');
						const reqBar = Math.max(6, Math.round(((m.requests ?? 0) / maxReq) * 100));
						return (
							<tr key={`${m.provider ?? ''}/${m.model ?? ''}-${i}`} className="border-b border-line/60">
								<Td>
									<span className="inline-flex items-center gap-1.5">
										<span
											aria-hidden
											className="h-2 w-2 shrink-0 rounded-[2px]"
											style={{background: color}}
										/>
										{shortModel(m.model)}
									</span>
								</Td>
								<Td>{m.provider ?? NO_DATA}</Td>
								<Td num>
									<span className="inline-flex items-center justify-end gap-1.5">
										<span
											aria-hidden
											className="h-[3px] w-10 overflow-hidden rounded-full bg-glass"
										>
											<span
												className="block h-full"
												style={{
													width: `${Math.round((m.hit_rate ?? 0) * 100)}%`,
													background: color,
												}}
											/>
										</span>
										{rateLabel(m)}
									</span>
								</Td>
								<Td num>
									{m.cache_hit == null || m.cache_miss == null
										? NO_DATA
										: `${compactToken(m.cache_hit)} / ${compactToken(m.cache_hit + m.cache_miss)}`}
								</Td>
								<Td num>
									<span className="inline-flex items-center justify-end gap-1.5">
										<span aria-hidden className="h-[3px] w-10 overflow-hidden rounded-full bg-glass">
											<span
												className="block h-full"
												style={{width: `${reqBar}%`, background: color}}
											/>
										</span>
										{intLabel(m.requests)}
									</span>
								</Td>
								<Td num>{tokenLabel(m.output)}</Td>
								<Td num>{costLabel(m.cost_cny, m.cost_unknown_requests)}</Td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}

function Th({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<th
			className={cn(
				'whitespace-nowrap px-3 py-1.5 font-normal text-mute',
				num ? 'text-right' : 'text-left',
			)}
		>
			{children}
		</th>
	);
}

function Td({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<td className={cn('px-3 py-1.5', num ? 'text-right tabular-nums' : 'text-left')}>{children}</td>
	);
}
