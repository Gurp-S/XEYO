import {beforeEach, describe, expect, it} from 'vitest';
import {useNavJournalStore, type NavEntry} from './navJournalStore';

const e = (path: string, usageOpen = false): NavEntry => ({path, usageOpen});

function reset() {
	useNavJournalStore.setState({entries: [], index: -1});
}

describe('navJournalStore', () => {
	beforeEach(reset);

	it('records pushes and tracks index', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a'));
		s.record(e('/c/b'));
		s.record(e('/c/c'));
		expect(useNavJournalStore.getState().entries.map(x => x.path)).toEqual([
			'/c/a',
			'/c/b',
			'/c/c',
		]);
		expect(useNavJournalStore.getState().index).toBe(2);
	});

	it('same entry is idempotent', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a', true));
		s.record(e('/c/a', true));
		expect(useNavJournalStore.getState().entries.length).toBe(1);
		expect(useNavJournalStore.getState().index).toBe(0);
	});

	it('neighbor match moves pointer back/forward instead of pushing', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a'));
		s.record(e('/c/b'));
		// 回到 a：识别为后退
		s.record(e('/c/a'));
		expect(useNavJournalStore.getState().index).toBe(0);
		expect(useNavJournalStore.getState().entries.length).toBe(2);
		// 再到 b：识别为前进
		s.record(e('/c/b'));
		expect(useNavJournalStore.getState().index).toBe(1);
	});

	it('new visit after back truncates forward branch', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a'));
		s.record(e('/c/b'));
		s.record(e('/c/c'));
		s.record(e('/c/b')); // 邻居匹配 → 后退一步（index 1）
		expect(useNavJournalStore.getState().index).toBe(1);
		s.record(e('/side/x')); // 新访问 → 截断 forward 分支（c）
		const st = useNavJournalStore.getState();
		expect(st.entries.map(x => x.path)).toEqual(['/c/a', '/c/b', '/side/x']);
		expect(st.index).toBe(2);
	});

	it('usage toggle creates a distinct screen and restores via neighbor match', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a', false));
		s.record(e('/c/a', true)); // 开用量面板 = 新界面
		let st = useNavJournalStore.getState();
		expect(st.entries.length).toBe(2);
		expect(st.index).toBe(1);
		st.record(e('/c/a', false)); // 关闭 → 邻居匹配后退
		st = useNavJournalStore.getState();
		expect(st.index).toBe(0);
		expect(st.entries.length).toBe(2);
	});

	it('far-back revisit pushes a fresh entry (no pointer jumping)', () => {
		const s = useNavJournalStore.getState();
		s.record(e('/c/a'));
		s.record(e('/c/b'));
		s.record(e('/c/c'));
		// 直接点侧栏回到最早的 a（非邻居）→ 视为新访问入栈，指针跳到尾部。
		s.record(e('/c/a'));
		const st = useNavJournalStore.getState();
		expect(st.index).toBe(3);
		expect(st.entries.map(x => x.path)).toEqual([
			'/c/a',
			'/c/b',
			'/c/c',
			'/c/a',
		]);
	});

	it('caps history at 200 entries keeping the tail', () => {
		const s = useNavJournalStore.getState();
		for (let i = 0; i < 205; i += 1) {
			s.record(e(`/c/s${i}`));
		}
		const st = useNavJournalStore.getState();
		expect(st.entries.length).toBe(200);
		expect(st.entries[0]!.path).toBe('/c/s5');
		expect(st.index).toBe(199);
	});

	it('peekBack/peekForward honor boundaries', () => {
		const s = useNavJournalStore.getState();
		expect(s.peekBack()).toBeNull();
		s.record(e('/c/a'));
		s.record(e('/c/b'));
		s.record(e('/c/c'));
		expect(s.peekBack()?.path).toBe('/c/b');
		expect(s.peekForward()).toBeNull();
	});
});
