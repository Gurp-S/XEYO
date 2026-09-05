"""Playwright 生命周期：持久化登录、抽 QR、轮询入站、发文本/文件。

Windows 上微信登录 QR 需要真实 Chrome/Edge 窗口（可移到屏幕外）。
默认先 headed，仅在显式 XEYO_FILEHELPER_HEADLESS=1 时强制无头。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from channels.filehelper.commands import help_text, parse_command
from common.errors import friendly_error
from channels.filehelper.page import (
	capture_qr_png,
	chunk_text,
	goto_home,
	inspect,
	install_chat_watch,
	qr_expired,
	read_chat_text,
	refresh_qr,
	send_file as page_send_file,
	send_text as page_send_text,
)
from channels.filehelper.prefix import is_own_reply, xeyo_reply
from channels.filehelper.seen import SeenIndex, added_messages, seen_store_path

State = str  # stopped | starting | qr | scanned | logged_in | error

InboundHandler = Callable[[str], Coroutine[Any, Any, None]]
StateListener = Callable[[], None]

_CHROME_UA = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_STEALTH_JS = """Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
Object.defineProperty(document, 'hidden', { get: () => false });
Object.defineProperty(document, 'visibilityState', { get: () => 'visible' });
"""

_QR_WAIT_HINT = (
	"仍未出现二维码。请确认已安装 Google Chrome，关闭后重试。"
)

_LAUNCH_TIMEOUT_MS = 12_000
_CREATE_NO_WINDOW = 0x08000000


def _truthy(name: str) -> bool:
	return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _force_headless() -> bool:
	return _truthy("XEYO_FILEHELPER_HEADLESS")


def _install_no_window_subprocess() -> None:
	"""Hide Playwright node.exe / browser helper consoles on Windows."""
	if sys.platform != "win32":
		return
	if getattr(asyncio, "_xeyo_no_window", False):
		return

	orig = asyncio.create_subprocess_exec

	async def _hidden(*args: Any, **kwargs: Any):
		kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | _CREATE_NO_WINDOW
		si = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
		si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		si.wShowWindow = subprocess.SW_HIDE
		kwargs["startupinfo"] = si
		return await orig(*args, **kwargs)

	asyncio.create_subprocess_exec = _hidden  # type: ignore[method-assign]
	asyncio._xeyo_no_window = True  # type: ignore[attr-defined]


def _browser_args(*, headless: bool) -> list[str]:
	args = [
		"--disable-blink-features=AutomationControlled",
		"--no-first-run",
		"--no-default-browser-check",
		"--disable-dev-shm-usage",
		"--disable-extensions",
		"--disable-breakpad",
		"--disable-crash-reporter",
		"--disable-logging",
		"--log-level=3",
	]
	if not headless:
		args.extend(
			[
				"--window-position=24000,24000",
				"--window-size=900,720",
			]
		)
	return args


def _clear_profile_locks(profile: Path) -> None:
	for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
		try:
			(profile / name).unlink(missing_ok=True)
		except OSError:
			pass


def _launch_cache_path() -> Path:
	return profile_dir() / ".launch_ok"


def _cached_launch_kind() -> str:
	try:
		return _launch_cache_path().read_text(encoding="utf-8").strip()
	except OSError:
		return ""


def _remember_launch_kind(kind: str) -> None:
	try:
		_launch_cache_path().write_text(kind, encoding="utf-8")
	except OSError:
		pass


def _clear_launch_cache() -> None:
	try:
		_launch_cache_path().unlink(missing_ok=True)
	except OSError:
		pass


def _launch_attempts(*, force_headless: bool, prefer_headed: bool) -> list[dict[str, Any]]:
	headed_ok = not force_headless
	headless_attempts: list[dict[str, Any]] = [
		{"kind": "chrome-headless", "channel": "chrome", "headless": True},
		{"kind": "edge-headless", "channel": "msedge", "headless": True},
		{"kind": "chromium-headless", "headless": True},
	]
	headed_attempts: list[dict[str, Any]] = [
		{"kind": "chrome-headed", "channel": "chrome", "headless": False},
		{"kind": "edge-headed", "channel": "msedge", "headless": False},
		{"kind": "chromium-headed", "headless": False},
	]
	if not headed_ok:
		return headless_attempts
	if prefer_headed or sys.platform == "win32":
		attempts = headed_attempts + headless_attempts
	else:
		attempts = headless_attempts + headed_attempts
	cached = _cached_launch_kind()
	if cached and not prefer_headed:
		if sys.platform == "win32" and "headless" in cached:
			pass
		else:
			attempts.sort(key=lambda a: 0 if a["kind"] == cached else 1)
	return attempts


async def _launch_persistent(
	playwright: Any,
	profile: Path,
	*,
	prefer_headed: bool = False,
) -> tuple[Any, str]:
	force_headless = _force_headless()
	errors: list[str] = []
	last: Exception | None = None
	for spec in _launch_attempts(force_headless=force_headless, prefer_headed=prefer_headed):
		_clear_profile_locks(profile)
		headless = bool(spec["headless"])
		opts: dict[str, Any] = {
			"headless": headless,
			"viewport": {"width": 900, "height": 720},
			"user_agent": _CHROME_UA,
			"locale": "zh-CN",
			"ignore_default_args": ["--enable-automation"],
			"args": _browser_args(headless=headless),
			"timeout": _LAUNCH_TIMEOUT_MS,
		}
		if spec.get("channel"):
			opts["channel"] = spec["channel"]
		try:
			ctx = await playwright.chromium.launch_persistent_context(str(profile), **opts)
			_remember_launch_kind(str(spec["kind"]))
			return ctx, str(spec["kind"])
		except Exception as e:  # noqa: BLE001
			last = e
			errors.append(f"{spec['kind']}: {type(e).__name__}")
			continue
	detail = "; ".join(errors) if errors else "unknown"
	raise RuntimeError(f"unable to launch browser ({detail})") from last


async def _park_window(context: Any, page: Any) -> None:
	try:
		session = await context.new_cdp_session(page)
		info = await session.send("Browser.getWindowForTarget")
		wid = info.get("windowId")
		if wid is None:
			return
		await session.send(
			"Browser.setWindowBounds",
			{
				"windowId": wid,
				"bounds": {
					"left": 24000,
					"top": 24000,
					"width": 900,
					"height": 720,
					"windowState": "normal",
				},
			},
		)
	except Exception:
		pass


def filehelper_autostart() -> bool:
	return _truthy("XEYO_FILEHELPER")


def profile_dir() -> Path:
	raw = os.environ.get("XEYO_FILEHELPER_PROFILE", "").strip()
	if raw:
		return Path(raw)
	return Path(__file__).resolve().parents[2] / ".xeyo_filehelper"


class FileHelperBridge:
	def __init__(self) -> None:
		self.state: State = "stopped"
		self.error: str | None = None
		self.hint: str | None = None
		self._qr: bytes | None = None
		self._qr_rev = 0
		self._playwright: Any = None
		self._context: Any = None
		self._page: Any = None
		self._loop_task: asyncio.Task[None] | None = None
		# asyncio 原语不能在模块 import 时创建：它们会绑定创建时（可能不存在）
		# 的 loop，跨测试/跨 loop 复用会挂死。start() 在运行中的 loop 里重建。
		self._send_lock: asyncio.Lock | None = None
		self._seen = SeenIndex()
		self._last_chat = ""
		self._seeded = False
		self._on_inbound: InboundHandler | None = None
		self._on_command: Callable[[str, str], Coroutine[Any, Any, str | None]] | None = None
		self._on_state: StateListener | None = None
		self._stop: asyncio.Event | None = None
		self._started_at = 0.0
		self._launch_kind = ""
		self._relaunched_headed = False
		self._login_ticks = 0
		self._watch_installed = False
		self._inbound_debounce: asyncio.Task[None] | None = None
		self._pending_inbound: list[str] = []
		self._seen_path = seen_store_path(profile_dir())
		self._qr_misses = 0

	def _notify_state(self) -> None:
		cb = self._on_state
		if cb is not None:
			cb()

	@property
	def logged_in(self) -> bool:
		return self.state == "logged_in"

	def _send_lock_required(self) -> asyncio.Lock:
		if self._send_lock is None:
			raise RuntimeError("filehelper not started")
		return self._send_lock

	@property
	def running(self) -> bool:
		return self.state not in {"stopped"} and self._page is not None

	@property
	def qr_rev(self) -> int:
		return self._qr_rev

	def qr_png(self) -> bytes | None:
		return self._qr

	def _set_qr(self, png: bytes | None) -> None:
		if png == self._qr:
			return
		if png is not None:
			self._qr_rev += 1
		self._qr = png
		self._notify_state()

	def set_inbound_handler(self, handler: InboundHandler | None) -> None:
		self._on_inbound = handler

	def set_command_handler(
		self, handler: Callable[[str, str], Coroutine[Any, Any, str | None]] | None
	) -> None:
		self._on_command = handler

	def set_state_listener(self, listener: StateListener | None) -> None:
		self._on_state = listener

	async def start(self) -> None:
		if self.state in {"starting", "qr", "scanned", "logged_in"}:
			return
		# 绑定当前运行 loop 后重建原语（见 __init__ 注释）。
		self._stop = asyncio.Event()
		self._send_lock = asyncio.Lock()
		self.state = "starting"
		self.error = None
		self.hint = "正在启动 Chrome 后台窗口…"
		self._set_qr(None)
		self._seen = SeenIndex()
		self._seen.load(self._seen_path)
		self._last_chat = ""
		self._seeded = False
		self._started_at = time.monotonic()
		self._relaunched_headed = False
		self._launch_kind = ""
		self._qr_misses = 0
		if sys.platform == "win32" and "headless" in _cached_launch_kind():
			_clear_launch_cache()
		_install_no_window_subprocess()
		try:
			from playwright.async_api import async_playwright  # noqa: F401
		except ImportError as e:
			self.state = "error"
			self.error = (
				"playwright not installed — pip install playwright "
				"&& playwright install chromium"
			)
			raise RuntimeError(self.error) from e
		self._loop_task = asyncio.create_task(self._boot_and_loop())

	async def _boot_and_loop(self) -> None:
		try:
			await self._launch_browser(prefer_headed=sys.platform == "win32")
			if self._stop.is_set() or self._page is None:
				return
			self.hint = "正在打开微信网页…"
			await goto_home(self._page)
			if "headed" in self._launch_kind:
				await _park_window(self._context, self._page)
			info = await inspect(self._page)
			if info.get("loggedIn"):
				self.state = "logged_in"
				self._set_qr(None)
				self.error = None
				self.hint = None
				self._login_ticks = 0
				self._notify_state()
				await self._ensure_watch(self._page)
				await self._poll_messages(self._page)
			else:
				await self._tick(self._page)
			while not self._stop.is_set():
				page = self._page
				if page is None:
					break
				try:
					if await self._maybe_relaunch_headed():
						continue
					await self._tick(page)
				except asyncio.CancelledError:
					raise
				except Exception as e:  # noqa: BLE001
					self.state = "error"
					self.error = friendly_error(e)
				delay = 2.5 if self.state == "logged_in" and self._watch_installed else (
					0.9 if self.state == "logged_in" else 0.5
				)
				await asyncio.sleep(delay)
		except asyncio.CancelledError:
			return
		except Exception as e:  # noqa: BLE001
			self.state = "error"
			self.error = friendly_error(e)
			self._notify_state()

	async def _launch_browser(self, *, prefer_headed: bool = False) -> None:
		from playwright.async_api import async_playwright

		_install_no_window_subprocess()
		profile = profile_dir()
		profile.mkdir(parents=True, exist_ok=True)
		_clear_profile_locks(profile)
		if self._playwright is None:
			self._playwright = await async_playwright().start()
		self._context, self._launch_kind = await _launch_persistent(
			self._playwright, profile, prefer_headed=prefer_headed
		)
		self._page = (
			self._context.pages[0] if self._context.pages else await self._context.new_page()
		)
		await self._context.add_init_script(_STEALTH_JS)
		await self._page.add_init_script(_STEALTH_JS)
		try:
			await self._page.set_viewport_size({"width": 900, "height": 720})
		except Exception:
			pass
		if "headed" in self._launch_kind:
			await _park_window(self._context, self._page)

	async def _close_context(self) -> None:
		if self._context is not None:
			try:
				await self._context.close()
			except Exception:
				pass
		self._context = None
		self._page = None
		self._watch_installed = False

	async def _maybe_relaunch_headed(self) -> bool:
		if self._relaunched_headed or self._stop.is_set():
			return False
		if self.state not in {"starting"}:
			return False
		if self.state == "logged_in":
			return False
		if self._qr is not None:
			return False
		if "headless" not in self._launch_kind:
			return False
		if _force_headless():
			return False
		waited = time.monotonic() - self._started_at
		if waited < 2 and self._qr_misses < 2:
			return False
		self._relaunched_headed = True
		self.hint = "无头模式未出码，改用 Chrome 后台窗口…"
		_clear_launch_cache()
		await self._close_context()
		await self._launch_browser(prefer_headed=True)
		if self._page is None:
			return False
		await goto_home(self._page)
		if "headed" in self._launch_kind:
			await _park_window(self._context, self._page)
		await self._tick(self._page)
		return True

	async def stop(self) -> None:
		self._stop.set()
		task = self._loop_task
		self._loop_task = None
		if task is not None:
			task.cancel()
			try:
				await task
			except (asyncio.CancelledError, Exception):
				pass
		await self._close_context()
		if self._playwright is not None:
			try:
				await self._playwright.stop()
			except Exception:
				pass
		self._playwright = None
		self._set_qr(None)
		self.hint = None
		self.error = None
		self._launch_kind = ""
		self.state = "stopped"
		self._notify_state()

	async def send_text(self, text: str) -> None:
		page = self._page
		if page is None:
			raise RuntimeError("filehelper not running")
		chunks = chunk_text(text, 4000)
		async with self._send_lock_required():
			for chunk in chunks:
				self._seen.remember_outbound(chunk)
				self._seen.save(self._seen_path)
				await page_send_text(page, chunk)

	async def send_file(self, path: Path) -> None:
		page = self._page
		if page is None:
			raise RuntimeError("filehelper not running")
		async with self._send_lock_required():
			await page_send_file(page, path)

	async def dispatch_inbound(self, msg: str) -> None:
		if is_own_reply(msg):
			self._seen.remember_outbound(msg)
			return
		hit = parse_command(msg)
		if hit is None:
			handler = self._on_inbound
			if handler is not None:
				await handler(msg)
			return
		try:
			extra: str | None = None
			if self._on_command is not None:
				extra = await self._on_command(hit.name, msg)
			await self._run_command(hit.name, extra)
		except Exception as e:  # noqa: BLE001
			await self.send_text(xeyo_reply(f"{hit.name} 失败：{friendly_error(e)}"))

	async def _run_command(self, name: str, extra: str | None = None) -> None:
		if name == "help":
			await self.send_text(xeyo_reply(help_text()))
			return
		if extra:
			await self.send_text(xeyo_reply(extra))

	async def _flush_inbound(self) -> None:
		if self.state != "logged_in":
			self._pending_inbound.clear()
			return
		batch = self._pending_inbound[:]
		self._pending_inbound.clear()
		fresh = self._seen.take_inbound(batch)
		for msg in fresh:
			await self.dispatch_inbound(msg)
		if fresh:
			self._seen.save(self._seen_path)

	def _queue_inbound(self, text: str) -> None:
		t = (text or "").strip()
		if not t:
			return
		self._pending_inbound.append(t)
		task = self._inbound_debounce
		if task is not None and not task.done():
			task.cancel()

		async def _run() -> None:
			try:
				await asyncio.sleep(0.1)
				await self._flush_inbound()
			except asyncio.CancelledError:
				return

		self._inbound_debounce = asyncio.create_task(_run())

	async def _tick(self, page: Any) -> None:
		if self.state == "logged_in":
			self._login_ticks += 1
			if self._login_ticks % 6 == 1:
				info = await inspect(page)
				if not info.get("loggedIn"):
					self.hint = "微信已断开，请重新扫码"
					self.state = "starting"
					self._seeded = False
					self._watch_installed = False
					self._set_qr(None)
					try:
						await goto_home(page)
					except Exception:
						pass
					self._notify_state()
					return
			await self._ensure_watch(page)
			await self._poll_messages(page)
			return

		info = await inspect(page)
		if info.get("loggedIn"):
			self.state = "logged_in"
			self._set_qr(None)
			self.error = None
			self.hint = None
			self._login_ticks = 0
			self._notify_state()
			await self._ensure_watch(page)
			await self._poll_messages(page)
			return

		if info.get("scanned"):
			self.state = "scanned"
			self.error = None
			self.hint = None
			return

		if self.state == "qr" and self._qr is not None:
			if await qr_expired(page):
				await refresh_qr(page)
				self._set_qr(None)
			else:
				return

		if await qr_expired(page):
			await refresh_qr(page)
		png = await capture_qr_png(page)
		if png:
			self._qr_misses = 0
			self.state = "qr"
			self.error = None
			self.hint = None
			self._set_qr(png)
			return

		if not info.get("loggedIn") and not info.get("scanned"):
			self._qr_misses += 1
			if "headless" in self._launch_kind and self._qr_misses >= 3:
				_clear_launch_cache()
			if self._qr_misses in {3, 8}:
				try:
					await refresh_qr(page)
				except Exception:
					pass
			if self._qr_misses == 7:
				try:
					await goto_home(page)
				except Exception:
					pass

		waited = time.monotonic() - self._started_at if self._started_at else 0
		if info.get("loginPage"):
			self.hint = "页面已打开，正在截取二维码…" if waited < 12 else _QR_WAIT_HINT
			return
		if waited >= 12:
			self.hint = _QR_WAIT_HINT
		elif waited >= 2:
			self.hint = "正在打开微信网页…"

	async def _ensure_watch(self, page: Any) -> None:
		if self._watch_installed or page is None:
			return

		async def _from_page(text: str) -> None:
			t = (text or "").strip()
			if not t or self.state != "logged_in":
				return
			self._queue_inbound(t)

		self._watch_installed = await install_chat_watch(page, _from_page)

	async def _poll_messages(self, page: Any) -> None:
		text = await read_chat_text(page)
		if not self._seeded:
			self._seen.seed([ln.strip() for ln in text.splitlines() if ln.strip()])
			self._seen.save(self._seen_path)
			self._last_chat = text
			self._seeded = True
			return
		delta = added_messages(self._last_chat, text)
		self._last_chat = text
		if delta:
			self._queue_inbound("\n".join(delta))
