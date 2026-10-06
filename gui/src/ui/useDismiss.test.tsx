/**
 * `useDismiss` 是 15 处浮层共用的关闭配对，所以它的语义必须被钉住 ——
 * 各宿主的历史行为（谁 document、谁 pointerdown+capture、谁按 id/属性放行）
 * 就是这里的判据。
 *
 * 四条放行轴（keepOpenRefs / panelId / panelRef / keepOpenSelector）各自单独
 * 验证：harness 若同时接上多条，任一条绿都说明不了是哪条在起作用。
 */
import {act, render} from '@testing-library/react';
import {useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {describe, expect, it, vi} from 'vitest';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {useDismiss, type DismissArgs} from './useDismiss';

function Harness({
	args,
	portalId,
	onClosed,
	initialOpen = true,
	withPanelRef = false,
}: {
	args: Omit<DismissArgs, 'open' | 'onClose'>;
	/** 把面板 portal 到 body（于是不在触发器子树里）。 */
	portalId?: string;
	onClosed: () => void;
	initialOpen?: boolean;
	/** 只在验证 panelRef 这一条轴时才把面板句柄交回 hook。 */
	withPanelRef?: boolean;
}) {
	const [open, setOpen] = useState(initialOpen);
	const wrapRef = useRef<HTMLDivElement>(null);
	const panelRef = useRef<HTMLDivElement>(null);
	useDismiss({
		...args,
		open,
		onClose: () => {
			setOpen(false);
			onClosed();
		},
		keepOpenRefs: [wrapRef],
		...(withPanelRef ? {panelRef} : {}),
	});
	return (
		<>
			<div data-testid="wrap" ref={wrapRef}>
				inside
			</div>
			<div data-testid="outside">outside</div>
			{open && portalId
				? createPortal(
						<div id={portalId} data-probe-panel="" ref={panelRef} data-testid="panel">
							panel
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

const down = (el: Element, kind: 'mouse' | 'pointer' = 'mouse') => {
	act(() => {
		el.dispatchEvent(
			new MouseEvent(kind === 'mouse' ? 'mousedown' : 'pointerdown', {
				bubbles: true,
				cancelable: true,
			}),
		);
	});
};

describe('useDismiss', () => {
	it('外点一次 mousedown 就关，且关完不再监听', () => {
		const closed = vi.fn();
		const {getByTestId} = render(<Harness args={{escId: 'a'}} onClosed={closed} />);
		down(getByTestId('outside'));
		expect(closed).toHaveBeenCalledTimes(1);
		// 已关：再来一次不该重复触发（监听必须已经摘掉）
		down(getByTestId('outside'));
		expect(closed).toHaveBeenCalledTimes(1);
	});

	it('轴一：落在 keepOpenRefs 内部的点击不算外点', () => {
		const closed = vi.fn();
		const {getByTestId} = render(<Harness args={{escId: 'b'}} onClosed={closed} />);
		down(getByTestId('wrap'));
		expect(closed).not.toHaveBeenCalled();
	});

	it('轴二：panelId 放行 portal 面板（不给 panelRef，不靠 ref 兜住）', () => {
		const closed = vi.fn();
		const {getByTestId} = render(
			<Harness args={{escId: 'c', panelId: 'p1'}} portalId="p1" onClosed={closed} />,
		);
		down(getByTestId('panel'));
		expect(closed).not.toHaveBeenCalled();
		down(getByTestId('outside'));
		expect(closed).toHaveBeenCalledTimes(1);
	});

	it('轴三：panelRef 放行 portal 面板（不给 panelId）', () => {
		const closed = vi.fn();
		const {getByTestId} = render(
			<Harness args={{escId: 'c2'}} portalId="p2" withPanelRef onClosed={closed} />,
		);
		down(getByTestId('panel'));
		expect(closed).not.toHaveBeenCalled();
	});

	it('轴四：keepOpenSelector 放行多面板浮层（右键菜单 + 子菜单的形状）', () => {
		const closed = vi.fn();
		const {getByTestId, unmount} = render(
			<Harness
				args={{escId: 'c3', keepOpenSelector: '[data-probe-panel]'}}
				portalId="p3"
				onClosed={closed}
			/>,
		);
		down(getByTestId('panel'));
		expect(closed).not.toHaveBeenCalled();
		unmount();
	});

	it('轴四反向对照：不给 keepOpenSelector，同一记点击就会关', () => {
		// 上一条若单独看可能是空判据（面板被别的轴兜住了），这条把那种可能否掉。
		const closed = vi.fn();
		const {getByTestId} = render(<Harness args={{escId: 'c4'}} portalId="p4" onClosed={closed} />);
		down(getByTestId('panel'));
		expect(closed).toHaveBeenCalledTimes(1);
	});

	it('右键手势形态：pointerdown + capture，同一拍不开监听，下一拍才开', async () => {
		const closed = vi.fn();
		const {getByTestId} = render(
			<Harness
				args={{escId: 'd', dismissOn: 'pointerdown', capture: true, arm: 'nextTick'}}
				onClosed={closed}
			/>,
		);
		// 打开浮层的那一次按下不能把它关掉
		down(getByTestId('outside'), 'pointer');
		expect(closed).not.toHaveBeenCalled();
		await act(async () => {
			await new Promise(r => setTimeout(r, 0));
		});
		down(getByTestId('outside'), 'pointer');
		expect(closed).toHaveBeenCalledTimes(1);
	});

	it('Esc 只关最上层：下层浮层不受影响（escStack 后进先出）', () => {
		const lower = vi.fn();
		const upper = vi.fn();
		pushEscLayer('lower', lower);
		render(<Harness args={{escId: 'upper'}} onClosed={upper} />);
		act(() => {
			window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
		});
		expect(upper).toHaveBeenCalledTimes(1);
		expect(lower).not.toHaveBeenCalled();
		popEscLayer('lower');
	});

	it('卸载后外点不再回调', () => {
		const closed = vi.fn();
		const {unmount} = render(<Harness args={{escId: 'e'}} onClosed={closed} />);
		unmount();
		// 用仍挂在文档上的节点当事件源：卸载后的引用已经脱离文档，
		// 在它上面派发根本冒泡不到 document，那条断言会是空的。
		down(document.body);
		expect(closed).not.toHaveBeenCalled();
	});

	it('open=false 时不挂监听：外点不回调', () => {
		const closed = vi.fn();
		const {getByTestId, unmount} = render(
			<Harness args={{escId: 'f'}} onClosed={closed} initialOpen={false} />,
		);
		down(getByTestId('outside'));
		expect(closed).not.toHaveBeenCalled();
		unmount();
		// 探针非空前置：同一条事件在 open=true 时确实会关，否则上面那条是空判据
		const opened = vi.fn();
		const r2 = render(<Harness args={{escId: 'g'}} onClosed={opened} />);
		down(r2.getByTestId('outside'));
		expect(opened).toHaveBeenCalledTimes(1);
	});
});
