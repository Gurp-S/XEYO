/**
 * 原生 <dialog> 承载的轻量确认/输入弹窗（框架无关，返回 Promise）。
 * 与 WorkspaceRevertDialog 同一机制：showModal + ::backdrop + Esc=cancel 事件。
 * 视觉与现有浮层同语言：glass-strong 表面 + line 描边 + 14px 圆角 + 浮层级阴影。
 */

import {cssDurationMs} from './motionDuration';

export interface ConfirmDialogOptions {
	title: string;
	body?: string;
	confirmText?: string;
	cancelText?: string;
	danger?: boolean;
}

export interface PromptDialogOptions {
	title: string;
	placeholder?: string;
	initial?: string;
	confirmText?: string;
	cancelText?: string;
}

let styleInjected = false;

function ensureStyle() {
	if (styleInjected || typeof document === 'undefined') {
		return;
	}
	styleInjected = true;
	const el = document.createElement('style');
	el.id = 'xy-inline-dialog-style';
	el.textContent = `
dialog.xy-inline-dialog {
  border: none;
  padding: 0;
  background: transparent;
}
dialog.xy-inline-dialog::backdrop {
  background: rgb(31 41 55 / 0.28);
}
.xy-id-card {
  font-family: var(--font-sans);
  color: var(--xy-ink);
  width: min(88vw, 380px);
  padding: 18px 20px;
  border-radius: 14px;
  border: 1px solid var(--xy-line);
  background: var(--xy-glass-strong);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
  box-shadow:
    0 0 0 1px rgb(31 41 55 / 0.05),
    0 16px 40px rgb(31 41 55 / 0.16);
  transition:
    opacity var(--duration-fast, 140ms) var(--ease-out-soft),
    transform var(--duration-fast, 140ms) var(--ease-out-soft);
}
/* 退出动画：与入场 .anim-pop 镜像对称。animation 必须置 none——
   .anim-pop 的 both 填充会持续压住 opacity/transform，过渡无从生效。 */
.xy-id-card.xy-id-closing {
  animation: none;
  opacity: 0;
  transform: scale(0.98);
  pointer-events: none;
}
html[data-smoothness="off"] .xy-id-card.xy-id-closing {
  transition: none;
}
@media (prefers-reduced-motion: reduce) {
  .xy-id-card.xy-id-closing {
    transition: none;
  }
}
.xy-id-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--xy-ink);
}
.xy-id-body {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--xy-ink-soft);
  overflow-wrap: anywhere;
}
.xy-id-input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid var(--xy-line);
  background: color-mix(in srgb, var(--xy-paper) 45%, transparent);
  color: var(--xy-ink);
  font-family: inherit;
  font-size: 13.5px;
  outline: none;
  transition:
    border-color 160ms var(--ease-out-soft),
    box-shadow 160ms var(--ease-out-soft);
}
.xy-id-input:focus {
  border-color: var(--xy-accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--xy-accent) 22%, transparent);
}
.xy-id-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.xy-id-btn {
  padding: 6px 16px;
  border-radius: 10px;
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
  transition:
    background-color 140ms var(--ease-out-soft),
    color 140ms var(--ease-out-soft),
    border-color 140ms var(--ease-out-soft);
}
.xy-id-cancel {
  border: 1px solid var(--xy-line);
  background: transparent;
  color: var(--xy-mute);
}
.xy-id-cancel:hover {
  color: var(--xy-ink);
  border-color: color-mix(in srgb, var(--xy-ink) 40%, transparent);
}
.xy-id-confirm {
  border: none;
  background: var(--xy-accent);
  color: var(--xy-on-accent);
  font-weight: 600;
}
.xy-id-confirm:hover {
  background: var(--xy-accent-hover);
}
.xy-id-confirm.xy-id-danger {
  background: var(--xy-danger);
}
.xy-id-confirm.xy-id-danger:hover {
  background: color-mix(in srgb, var(--xy-danger) 84%, black);
}
`;
	document.head.appendChild(el);
}

/** 组装卡片骨架；所有动态文案经 textContent 写入，不进 innerHTML。 */
function buildCard(title: string, body?: string): {dlg: HTMLDialogElement; card: HTMLElement} {
	ensureStyle();
	const dlg = document.createElement('dialog');
	dlg.className = 'xy-inline-dialog';
	const card = document.createElement('div');
	card.className = 'xy-id-card anim-pop';
	const h2 = document.createElement('h2');
	h2.className = 'xy-id-title';
	h2.textContent = title;
	card.appendChild(h2);
	if (body) {
		const p = document.createElement('p');
		p.className = 'xy-id-body';
		p.textContent = body;
		card.appendChild(p);
	}
	dlg.appendChild(card);
	return {dlg, card};
}

function buildActions(card: HTMLElement, cancelText: string, confirmText: string, danger: boolean) {
	const actions = document.createElement('div');
	actions.className = 'xy-id-actions';
	const cancel = document.createElement('button');
	cancel.type = 'button';
	cancel.className = 'xy-id-btn xy-id-cancel';
	cancel.textContent = cancelText;
	const ok = document.createElement('button');
	ok.type = 'button';
	ok.className = `xy-id-btn xy-id-confirm${danger ? ' xy-id-danger' : ''}`;
	ok.textContent = confirmText;
	actions.append(cancel, ok);
	card.appendChild(actions);
	return {cancel, ok};
}

function showModal(dlg: HTMLDialogElement) {
	document.body.appendChild(dlg);
	dlg.showModal();
}

/**
 * 关闭并移除：先播退出过渡，再 close + remove。
 * 原先 finish() 直接 close+remove，弹窗瞬消，是全 GUI 唯一无退场动画的浮层，
 * 与入场 .anim-pop 不对称。Promise 仍同步 resolve，调用方无需等待动画。
 */
function dismissCard(dlg: HTMLDialogElement, card: HTMLElement) {
	card.classList.add('xy-id-closing');
	window.setTimeout(() => {
		try {
			dlg.close();
		} catch {
			/* 已关闭 */
		}
		dlg.remove();
	}, cssDurationMs('fast'));
}

/** Esc 走原生 cancel 事件。 */
function bindCancel(dlg: HTMLDialogElement, onCancel: () => void) {
	dlg.addEventListener('cancel', e => {
		e.preventDefault();
		onCancel();
	});
}

/** Enter 确认；焦点落在取消钮时交给按钮自身行为。 */
function bindEnter(dlg: HTMLDialogElement, cancel: HTMLButtonElement, onConfirm: () => void) {
	dlg.addEventListener('keydown', e => {
		if (e.key === 'Enter' && !e.defaultPrevented && e.target !== cancel) {
			e.preventDefault();
			onConfirm();
		}
	});
}

export function confirmDialog(o: ConfirmDialogOptions): Promise<boolean> {
	return new Promise(resolve => {
		const {dlg, card} = buildCard(o.title, o.body);
		const {cancel, ok} = buildActions(
			card,
			o.cancelText ?? '取消',
			o.confirmText ?? '确定',
			o.danger === true,
		);
		let settled = false;
		const finish = (v: boolean) => {
			if (settled) {
				return;
			}
			settled = true;
			dismissCard(dlg, card); // 过渡结束即 close+remove，仍不移除泄漏
			resolve(v);
		};
		cancel.addEventListener('click', () => finish(false));
		ok.addEventListener('click', () => finish(true));
		bindCancel(dlg, () => finish(false));
		bindEnter(dlg, cancel, () => finish(true));
		showModal(dlg);
		ok.focus();
	});
}

export function promptDialog(o: PromptDialogOptions): Promise<string | null> {
	return new Promise(resolve => {
		const {dlg, card} = buildCard(o.title);
		const input = document.createElement('input');
		input.type = 'text';
		input.className = 'xy-id-input';
		input.placeholder = o.placeholder ?? '';
		input.value = o.initial ?? '';
		input.autocomplete = 'off';
		input.spellcheck = false;
		card.appendChild(input);
		const {cancel, ok} = buildActions(
			card,
			o.cancelText ?? '取消',
			o.confirmText ?? '确定',
			false,
		);
		let settled = false;
		const finish = (v: string | null) => {
			if (settled) {
				return;
			}
			settled = true;
			dismissCard(dlg, card);
			resolve(v);
		};
		const confirm = () => {
			const value = input.value.trim();
			if (!value) {
				input.focus();
				return;
			}
			finish(value);
		};
		cancel.addEventListener('click', () => finish(null));
		ok.addEventListener('click', confirm);
		input.addEventListener('keydown', e => {
			if (e.key === 'Enter') {
				e.preventDefault();
				confirm();
			}
		});
		bindCancel(dlg, () => finish(null));
		showModal(dlg);
		input.focus();
		input.select();
	});
}
