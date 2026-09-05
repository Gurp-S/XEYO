import {describe, expect, it} from 'vitest';
import {parseXeyoMapFence} from './xeyoMapFence';

describe('parseXeyoMapFence', () => {
	it('accepts architecture docs with file anchors', () => {
		const doc = parseXeyoMapFence(
			JSON.stringify({
				kind: 'architecture',
				title: 'demo',
				nodes: [
					{id: 'a', label: 'A', lane: 'ui', file: 'gui/src/a.ts'},
					{id: 'b', label: 'B', lane: 'api'},
				],
				edges: [{from: 'a', to: 'b'}],
			}),
		);
		expect(doc?.kind).toBe('architecture');
		expect(doc?.nodes).toHaveLength(2);
		expect(doc?.nodes[0]?.file).toBe('gui/src/a.ts');
	});

	it('rejects unknown kind', () => {
		expect(
			parseXeyoMapFence(
				JSON.stringify({kind: 'pizza', nodes: [{id: 'a', label: 'A'}], edges: []}),
			),
		).toBeNull();
	});
});
