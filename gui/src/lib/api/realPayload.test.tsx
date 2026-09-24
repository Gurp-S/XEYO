/**
 * 用真实数据生成的载荷打前端解析层与标签层。
 *
 * 这个文件存在的理由：其余测试的载荷都是作者自己写的夹具，所以它们只会重复作者的
 * 误解——真实数据上先后查出过 usage_by_attempt 永远为空、`folded_out` 没进中文标签表、
 * 覆盖状态被压成两档这类问题，没有一个能被自造夹具发现。
 */
import {render, screen} from '@testing-library/react';
import type {ReactElement} from 'react';
import {describe, expect, it} from 'vitest';

import {parseRunDetail} from './diagnostics';
import {realRunDetail} from '@/lib/api/__fixtures__/realRunDetail';
import {ContextView} from '@/features/diagnostics/ContextView';
import {FindingsView} from '@/features/diagnostics/FindingsView';
import {UsageView} from '@/features/diagnostics/UsageView';

const detail = parseRunDetail(realRunDetail);

describe('真实载荷 · 解析层', () => {
	it('服务端真发出来的形状能解析出各段内容', () => {
		expect(detail.session_id).toBe('sess_mubdqg8h_b4z3tx');
		expect(detail.turn_id).toBe('6d5b62115c99');
		expect(detail.findings.length).toBeGreaterThan(0);
		expect(detail.model_requests.length).toBeGreaterThan(0);
		expect(Object.keys(detail.coverage).length).toBeGreaterThan(0);
		expect(detail.fault).toBeTruthy();
		expect(detail.attribution).toBeTruthy();
		expect(detail.usage_summary).toBeTruthy();
	});

	it('每条结论都带可核对的身份', () => {
		for (const f of detail.findings) {
			expect(f.rule_id).toMatch(/^[a-z_]+$/);
			expect(['confirmed_fault', 'suspected_cause', 'unknown']).toContain(f.status);
			expect(f.phenomenon.length).toBeGreaterThan(0);
		}
	});

	it('覆盖状态只能是枚举内的值', () => {
		const known = new Set([
			'full',
			'partial',
			'absent',
			'redacted',
			'expired',
			'not_captured',
		]);
		for (const [source, c] of Object.entries(detail.coverage)) {
			expect(known.has(c.state), `${source} 出现了前端没准备标签的状态 ${c.state}`).toBe(
				true,
			);
		}
	});

	it('逐次用量真的连上了账（曾经的顺序 bug）', () => {
		const attached = detail.model_requests.filter(
			m => Object.keys(m.usage_by_attempt ?? {}).length > 0,
		);
		expect(attached.length).toBeGreaterThan(0);
	});
});

describe('真实载荷 · 标签层', () => {
	it('三个视图渲染真实数据时不把机器名投给用户', () => {
		// 这些是后端真的会发出来的枚举值；每一个都必须在中文标签表里有对应项。
		const machineTokens = [
			'confirmed_fault',
			'suspected_cause',
			'not_determined',
			'folded_out',
			'not_shown',
			'unprovable',
			'out_of_window',
			'source_absent',
			'not_captured',
			'read_failed',
			'no_turn_records',
		];
		const views: [string, ReactElement][] = [
			['问题', <FindingsView detail={detail} />],
			[
				'上下文',
				<ContextView
					detail={detail}
					sessionId={detail.session_id}
					turnId={detail.turn_id}
					storeRoot=''
				/>,
			],
			['用量', <UsageView detail={detail} />],
		];
		for (const [name, element] of views) {
			const {container, unmount} = render(element);
			const text = container.textContent ?? '';
			for (const token of machineTokens) {
				expect(text.includes(token), `${name} 视图漏出机器名 ${token}`).toBe(false);
			}
			expect(text).not.toMatch(/undefined|NaN|\[object Object]/);
			unmount();
		}
	});

	it('费用没有依据时不写成 ¥0', () => {
		const summary = detail.usage_summary as Record<string, unknown>;
		const unknowns = Number(summary.unknown_cost_attempts ?? 0);
		const {container} = render(<UsageView detail={detail} />);
		const text = container.textContent ?? '';
		if (unknowns > 0) {
			expect(screen.queryByText(/费用未知|未知/)).not.toBeNull();
			expect(text).not.toMatch(/¥\s*0(\.0+)?(?![\d.])/);
		}
		expect(text.length).toBeGreaterThan(0);
	});
});
