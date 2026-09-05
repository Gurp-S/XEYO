import {useEffect, useRef} from 'react';

type Fn = () => void;

const listeners = new Set<Fn>();
let timer = 0;

/** 全局 1s 心跳:多组件共享同一个 setInterval,最后一个订阅者离开即停表。
    替代各组件自建秒级定时器——并存 N 个=主线程每秒被唤醒 N 次,
    收敛后空闲(无订阅)时零唤醒,省电且降低渲染 jitter。 */
export function subscribeHeartbeat(fn: Fn): () => void {
	listeners.add(fn);
	if (!timer) {
		timer = window.setInterval(() => {
			for (const listener of [...listeners]) {
				listener();
			}
		}, 1000);
	}
	return () => {
		listeners.delete(fn);
		if (listeners.size === 0 && timer) {
			window.clearInterval(timer);
			timer = 0;
		}
	};
}

/** React 绑定:active=false 时不占心跳;回调经 ref 保持最新,不因闭包重订阅。 */
export function useHeartbeat(onTick: Fn, active = true): void {
	const ref = useRef(onTick);
	ref.current = onTick;
	useEffect(() => {
		if (!active) {
			return;
		}
		return subscribeHeartbeat(() => ref.current());
	}, [active]);
}
