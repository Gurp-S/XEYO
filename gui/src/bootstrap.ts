import {isTauri} from './lib/tauri';
import {waitForDesktopBackend} from './lib/desktopStartup';
import './styles/startup.css';

const root = document.getElementById('root')!;
const shell = document.createElement('div');
shell.className = 'xy-startup';
const title = document.createElement('strong'); title.textContent = 'XEYO';
const status = document.createElement('p'); status.setAttribute('role', 'status'); status.textContent = '正在打开…';
const retry = document.createElement('button'); retry.textContent = '重新加载'; retry.hidden = true;
retry.onclick = () => location.reload();
shell.append(title, status, retry); root.append(shell);
const controller = new AbortController();
window.addEventListener('pagehide', () => controller.abort(), {once: true});

// Start loading the application at once, in parallel with native service startup.
const application = import('./main');
const ready = isTauri() ? (async () => {
	const [{invoke}, {getCurrentWindow}] = await Promise.all([import('@tauri-apps/api/core'), import('@tauri-apps/api/window')]);
	const window = getCurrentWindow();
	const close = document.createElement('button'); close.className = 'xy-startup-close';
	close.textContent = '×'; close.setAttribute('aria-label', '关闭'); close.onclick = () => void window.close(); shell.append(close);
	// Hidden WebViews can suspend animation frames. The styled shell is already
	// in the DOM; show it before waiting on frames or backend readiness.
	await window.show();
	status.textContent = '正在启动服务…';
	await waitForDesktopBackend(() => invoke<boolean>('backend_startup_ready'), controller.signal);
})() : Promise.resolve();

let mounting = false;
async function mount() {
	const app = await application;
	if (controller.signal.aborted || mounting) return;
	mounting = true;
	try { await app.mountApp(); } catch (error) { mounting = false; throw error; }
}
void Promise.all([application, ready]).then(() => {
	return mount();
}).catch((error: unknown) => {
	if (controller.signal.aborted) return;
	status.textContent = `启动未完成：${error instanceof Error ? error.message : String(error)}`;
	retry.hidden = false;
	// A service failure must not remove access to already saved local history.
	void application.then(() => {
		if (controller.signal.aborted) return;
		const offline = document.createElement('button'); offline.textContent = '查看本地对话';
		offline.onclick = () => {void mount().catch(() => {retry.hidden = false;});}; shell.append(offline);
	}).catch(() => {});
});
