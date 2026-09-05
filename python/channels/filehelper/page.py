"""微信文件传输助手网页 DOM 操作。选择器集中在此，页面改版只改这一层。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from channels.filehelper import FILEHELPER_URL

_COMPOSER_CACHE: dict[int, Any] = {}
_SEND_CACHE: dict[int, Any] = {}

PLACEHOLDER_SNIPS = (
	"你可以使用",
	"使用手机微信扫码",
	"微信文件传输助手网页版",
	"二维码失效",
	"点击刷新",
	"切换帐号",
	"已扫码",
	"请在手机上",
)

# 走遍 light DOM + shadowRoot；「发送」在该页经常是 div 而不是 button。
_INSPECT_JS = """() => {
  const body = (document.body && (document.body.innerText || document.body.textContent) || '');
  const title = document.title || '';
  const hasSend = body.includes('发送');
  let hasComposer = Boolean(
    document.querySelector('textarea, [contenteditable="true"], [contenteditable="plaintext-only"]')
  );
  if (!hasComposer) {
    const walk = (root) => {
      if (!root || hasComposer) return;
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) walk(el.shadowRoot);
        const ce = el.getAttribute && el.getAttribute('contenteditable');
        if (ce === 'true' || ce === 'plaintext-only') hasComposer = true;
      }
    };
    walk(document);
  }
  const scanned = /已扫码|请在手机上确认|扫描成功|确认登录/.test(body);
  const loginChrome = /使用手机微信扫码|微信文件传输助手网页版|扫码传输文件|扫码登录|扫描二维码/.test(body);
  const placeholder = /与电脑互传文件/.test(body);
  const namedHelper = /的文件传输助手/.test(body) || /的文件传输助手/.test(title);
  const loggedIn = hasSend || (placeholder && !loginChrome);
  return {
    loggedIn: Boolean(loggedIn),
    scanned: Boolean(scanned && !loggedIn),
    loginPage: Boolean(loginChrome && !loggedIn),
    hasSend,
    placeholder,
  };
}"""

_READ_CHAT_JS = """() => {
  const drop = new Set(['发送', '...', '…', '帮助']);
  const skipSnips = ['你可以使用', '使用手机微信扫码', '微信文件传输助手网页版', '二维码失效', '点击刷新', '轻松互传文件'];
  const chromeRe = /^(?:上午|下午|凌晨|早上|晚上)?\\s*\\d{1,2}:\\d{2}$|^[\\d]{1,2}月[\\d]{1,2}日|^星期[一二三四五六日天]$|^(?:昨天|刚刚|今天)$/;
  const isOwn = (s) => /^\\s*\\[XEYO\\]/.test(s) || s.includes('\\n[XEYO]') || /^\\s*\\[远程\\]/.test(s);
  const keepLine = (s) => {
    if (!s || drop.has(s) || s.length > 8000) return false;
    if (isOwn(s) || chromeRe.test(s)) return false;
    if (skipSnips.some(p => s.includes(p))) return false;
    return true;
  };
  const findComposer = () => {
    const isBox = (el) => {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea' || (tag === 'input' && (el.type || 'text') === 'text')) return true;
      const ce = el.getAttribute && el.getAttribute('contenteditable');
      return ce === 'true' || ce === 'plaintext-only';
    };
    const walk = (root, last) => {
      if (!root) return last;
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) last = walk(el.shadowRoot, last);
        if (isBox(el)) last = el;
      }
      return last;
    };
    return walk(document, null);
  };
  const composer = findComposer();
  const cutY = composer ? composer.getBoundingClientRect().top - 6 : window.innerHeight - 120;
  const bubbles = [];
  const seen = new Set();
  const walk = (root) => {
    if (!root || !root.querySelectorAll) return;
    const nodes = root.querySelectorAll('*');
    for (const el of nodes) {
      if (el.shadowRoot) walk(el.shadowRoot);
      if (composer && (el === composer || composer.contains(el))) continue;
      const tag = (el.tagName || '').toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'textarea' || tag === 'input') continue;
      const r = el.getBoundingClientRect();
      if (!r || r.bottom > cutY || r.height < 10 || r.width < 24) continue;
      const t = (el.innerText || el.textContent || '').trim().replace(/\\r/g, '');
      if (!t || t.length > 4000 || seen.has(t)) continue;
      if (!keepLine(t.split('\\n').map(x => x.trim()).filter(Boolean).join('\\n'))) continue;
      if (el.children && el.children.length) {
        const childOnly = [...el.children].every(c => (c.innerText || '').trim().length > 0);
        if (childOnly && el.children.length > 1) continue;
      }
      seen.add(t);
      bubbles.push(t);
    }
  };
  walk(document);
  if (bubbles.length) return { text: bubbles.join('\\n') };
  const body = (document.body && (document.body.innerText || '') || '').replace(/\\r/g, '');
  const lines = body.split('\\n').map(s => s.trim()).filter(keepLine);
  return { text: lines.join('\\n') };
}"""

_WATCH_CHAT_JS = """() => {
  if (window.__xyChatWatch) return true;
  window.__xyChatWatch = true;
  const drop = new Set(['发送', '...', '…', '帮助']);
  const skipSnips = ['你可以使用', '使用手机微信扫码', '微信文件传输助手网页版', '二维码失效', '点击刷新', '轻松互传文件'];
  const chromeRe = /^(?:上午|下午|凌晨|早上|晚上)?\\s*\\d{1,2}:\\d{2}$|^[\\d]{1,2}月[\\d]{1,2}日|^星期[一二三四五六日天]$|^(?:昨天|刚刚|今天)$/;
  const isOwn = (s) => /^\\s*\\[XEYO\\]/.test(s) || s.includes('\\n[XEYO]') || /^\\s*\\[远程\\]/.test(s);
  const keep = (s) => {
    if (!s || drop.has(s) || s.length > 8000) return false;
    if (isOwn(s) || chromeRe.test(s)) return false;
    if (skipSnips.some(p => s.includes(p))) return false;
    return true;
  };
  const seen = new Set();
  const findComposer = () => {
    const isBox = (el) => {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea' || (tag === 'input' && (el.type || 'text') === 'text')) return true;
      const ce = el.getAttribute && el.getAttribute('contenteditable');
      return ce === 'true' || ce === 'plaintext-only';
    };
    const walk = (root, last) => {
      if (!root) return last;
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) last = walk(el.shadowRoot, last);
        if (isBox(el)) last = el;
      }
      return last;
    };
    return walk(document, null);
  };
  const collect = () => {
    const composer = findComposer();
    const cutY = composer ? composer.getBoundingClientRect().top - 6 : window.innerHeight - 120;
    const out = [];
    const local = new Set();
    const walk = (root) => {
      if (!root || !root.querySelectorAll) return;
      const nodes = root.querySelectorAll('*');
      for (const el of nodes) {
        if (el.shadowRoot) walk(el.shadowRoot);
        if (composer && (el === composer || composer.contains(el))) continue;
        const r = el.getBoundingClientRect();
        if (!r || r.bottom > cutY || r.height < 10 || r.width < 24) continue;
        const t = (el.innerText || el.textContent || '').trim().replace(/\\r/g, '');
        if (!t || local.has(t) || !keep(t)) continue;
        local.add(t);
        out.push(t);
      }
    };
    walk(document);
    if (!out.length) {
      const body = (document.body && document.body.innerText || '').replace(/\\r/g, '');
      body.split('\\n').map(s => s.trim()).filter(keep).forEach(s => out.push(s));
    }
    return out;
  };
  const scan = () => {
    const lines = collect();
    const fresh = [];
    for (const ln of lines) {
      if (seen.has(ln)) continue;
      seen.add(ln);
      fresh.push(ln);
    }
    if (seen.size > 400) {
      const keepSet = new Set(lines.slice(-200));
      seen.clear();
      keepSet.forEach(x => seen.add(x));
    }
    if (!fresh.length || typeof window.xeyoInbound !== 'function') return;
    for (const ln of fresh) window.xeyoInbound(ln);
  };
  collect().forEach(s => seen.add(s));
  let t = 0;
  const mo = new MutationObserver(() => {
    if (t) return;
    t = setTimeout(() => { t = 0; scan(); }, 60);
  });
  if (document.body) {
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  return true;
}"""

_TYPE_JS = """(text) => {
  const isBox = (el) => {
    if (!el || !el.tagName) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === 'textarea' || (tag === 'input' && (el.type || 'text') === 'text')) return true;
    const ce = el.getAttribute && el.getAttribute('contenteditable');
    return ce === 'true' || ce === 'plaintext-only';
  };
  const findBox = (root) => {
    if (!root) return null;
    const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
    let last = null;
    for (const el of nodes) {
      if (el.shadowRoot) {
        const inner = findBox(el.shadowRoot);
        if (inner) last = inner;
      }
      if (isBox(el)) last = el;
    }
    return last;
  };
  const box = findBox(document);
  if (!box) return false;
  box.focus();
  const tag = box.tagName.toLowerCase();
  if (tag === 'textarea' || tag === 'input') {
    const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(box, text);
    else box.value = text;
  } else {
    try {
      document.execCommand('selectAll', false, null);
      if (!document.execCommand('insertText', false, text)) {
        box.innerText = text;
        box.textContent = text;
      }
    } catch (e) {
      box.innerText = text;
      box.textContent = text;
    }
  }
  box.dispatchEvent(new InputEvent('input', {
    bubbles: true,
    cancelable: true,
    inputType: 'insertFromPaste',
    data: text,
  }));
  box.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}"""

_CLICK_SEND_JS = """() => {
  const hit = (root) => {
    if (!root) return false;
    const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of nodes) {
      if (el.shadowRoot && hit(el.shadowRoot)) return true;
      const t = (el.innerText || el.textContent || '').trim();
      if (t === '发送' || t === 'Send') {
        el.click();
        return true;
      }
    }
    return false;
  };
  return hit(document);
}"""

_QR_DATA_JS = """() => {
  const ok = (w, h) => w >= 100 && h >= 100 && Math.abs(w / h - 1) < 0.38;
  const looksQr = (el) => {
    const blob = [
      el.src || '',
      el.alt || '',
      el.className || '',
      el.id || '',
      el.getAttribute && (el.getAttribute('aria-label') || ''),
    ].join(' ').toLowerCase();
    return /qr|qrcode|二维码|weixin|wxcode|login|code/.test(blob);
  };
  const walkNodes = (root, acc) => {
    if (!root || !root.querySelectorAll) return;
    acc.push(...root.querySelectorAll('canvas'));
    acc.push(...root.querySelectorAll('img'));
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walkNodes(el.shadowRoot, acc);
    }
  };
  const nodes = [];
  walkNodes(document, nodes);
  let best = null;
  let bestArea = 0;
  let bestHint = false;
  for (const el of nodes) {
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'canvas') {
      const w = el.width || el.clientWidth || 0;
      const h = el.height || el.clientHeight || 0;
      if (!ok(w, h)) continue;
      const area = w * h;
      if (area <= bestArea) continue;
      try {
        const data = el.toDataURL('image/png');
        if (data) {
          bestArea = area;
          best = data;
          bestHint = false;
        }
      } catch (e) {}
      continue;
    }
    if (tag === 'img') {
      const r = el.getBoundingClientRect();
      if (!ok(r.width, r.height)) continue;
      const src = el.src || '';
      const hint = looksQr(el);
      if (!src.startsWith('data:image') && !hint) continue;
      if (!hint && Math.min(r.width, r.height) < 150) continue;
      const area = r.width * r.height;
      if (area <= bestArea) continue;
      bestArea = area;
      best = src;
      bestHint = hint;
    }
  }
  if (!best) return null;
  return { data: best, area: Math.round(bestArea), hint: bestHint };
}"""


async def _eval_frames(page: Any, js: str, arg: Any = None) -> list[Any]:
	out: list[Any] = []
	frames = list(getattr(page, "frames", []) or [])
	if not frames:
		frames = [page]
	for frame in frames:
		try:
			if arg is None:
				out.append(await frame.evaluate(js))
			else:
				out.append(await frame.evaluate(js, arg))
		except Exception:
			continue
	return out


async def goto_home(page: Any) -> None:
	await page.goto(FILEHELPER_URL, wait_until="domcontentloaded", timeout=25_000)
	try:
		await page.wait_for_function(
			"""() => {
			  const t = (document.body && document.body.innerText) || '';
			  const canvases = [...document.querySelectorAll('canvas')];
			  const hasCanvas = canvases.some(c => (c.width || 0) > 80);
			  return hasCanvas || /扫码|文件传输助手|发送/.test(t);
			}""",
			timeout=5_000,
		)
	except Exception:
		pass


def _png_from_data_url(data: str) -> bytes | None:
	if not data or not data.startswith("data:image"):
		return None
	try:
		raw = data.split(",", 1)[1]
		return base64.b64decode(raw)
	except Exception:
		return None


def _square_enough(box: dict[str, float] | None, *, min_px: float = 100) -> bool:
	if not box:
		return False
	w, h = float(box["width"]), float(box["height"])
	if w < min_px or h < min_px:
		return False
	ratio = w / max(h, 1)
	return 0.72 <= ratio <= 1.38


def _side_px(box: dict[str, float] | None) -> float:
	if not box:
		return 0.0
	return min(float(box["width"]), float(box["height"]))


def _is_icon_png(
	png: bytes,
	*,
	side: float = 0,
	area: int = 0,
	from_img: bool = False,
) -> bool:
	n = len(png)
	if n < 350:
		return True
	if side <= 0 and area > 0:
		side = float(area) ** 0.5
	if from_img and side > 0 and side < 140:
		return True
	if side > 0 and side < 90:
		return True
	# ≤118px 且 ≤800B 的小图基本是头像/图标（边界含等号：恰好 800B 也算）
	if side > 0 and side < 118 and n <= 800:
		return True
	return False


_QR_CLIP_JS = """() => {
  const ok = (w, h) => w >= 80 && h >= 80 && Math.abs(w / h - 1) < 0.42;
  let best = null;
  let bestArea = 0;
  const walk = (root) => {
    if (!root || !root.querySelectorAll) return;
    for (const c of root.querySelectorAll('canvas')) {
      const r = c.getBoundingClientRect();
      const w = r.width || c.clientWidth || 0;
      const h = r.height || c.clientHeight || 0;
      if (!ok(w, h)) continue;
      const area = w * h;
      if (area > bestArea) {
        bestArea = area;
        best = { x: r.x, y: r.y, width: w, height: h };
      }
    }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return best;
}"""


async def wait_for_login_qr(page: Any, *, timeout_ms: int = 1_500) -> None:
	try:
		await page.wait_for_function(
			"""() => {
			  const ok = (w, h) => w >= 100 && h >= 100;
			  const has = (root) => {
			    if (!root || !root.querySelectorAll) return false;
			    for (const c of root.querySelectorAll('canvas')) {
			      const w = c.width || c.clientWidth || 0;
			      const h = c.height || c.clientHeight || 0;
			      if (ok(w, h)) return true;
			    }
			    for (const el of root.querySelectorAll('*')) {
			      if (el.shadowRoot && has(el.shadowRoot)) return true;
			    }
			    return false;
			  };
			  return has(document);
			}""",
			timeout=timeout_ms,
		)
	except Exception:
		pass


async def capture_qr_png(page: Any) -> bytes | None:
	await wait_for_login_qr(page, timeout_ms=1_500)
	best: bytes | None = None
	best_rank = 0
	for raw in await _eval_frames(page, _QR_DATA_JS):
		area = 0
		from_img = False
		data_url = ""
		if isinstance(raw, dict):
			data_url = str(raw.get("data") or "")
			area = int(raw.get("area") or 0)
			from_img = bool(raw.get("hint"))
		elif raw:
			data_url = str(raw)
		png = _png_from_data_url(data_url)
		if not png or _is_icon_png(png, area=area, from_img=from_img):
			continue
		rank = area + len(png)
		if rank > best_rank:
			best = png
			best_rank = rank
	clip: dict[str, float] | None = None
	for raw in await _eval_frames(page, _QR_CLIP_JS):
		if isinstance(raw, dict) and raw.get("width") and raw.get("height"):
			clip = raw
			break
	if clip is not None:
		try:
			shot = await page.screenshot(
				type="png",
				clip={
					"x": float(clip["x"]),
					"y": float(clip["y"]),
					"width": float(clip["width"]),
					"height": float(clip["height"]),
				},
			)
			side = min(float(clip["width"]), float(clip["height"]))
			area = int(side * side)
			if shot and not _is_icon_png(shot, side=side, area=area) and len(shot) > best_rank:
				best = shot
				best_rank = len(shot) + area
		except Exception:
			pass
	if best:
		return best
	frames = list(getattr(page, "frames", []) or [page])
	targets = frames if frames else [page]
	for ctx in targets:
		try:
			loc = ctx.locator("canvas")
			n = await loc.count()
		except Exception:
			n = 0
		for i in range(min(n, 12)):
			el = loc.nth(i)
			try:
				if not await el.is_visible():
					continue
				box = await el.bounding_box()
				if not _square_enough(box, min_px=80):
					continue
				side = _side_px(box)
				area = int(side * side) if side else 0
				shot = await el.screenshot(type="png")
				if not shot or _is_icon_png(shot, side=side, area=area):
					continue
				rank = area + len(shot)
				if rank > best_rank:
					best = shot
					best_rank = rank
			except Exception:
				continue
		try:
			loc = ctx.locator("img")
			n = await loc.count()
		except Exception:
			continue
		for i in range(min(n, 12)):
			el = loc.nth(i)
			try:
				if not await el.is_visible():
					continue
				box = await el.bounding_box()
				if not _square_enough(box, min_px=120):
					continue
				side = _side_px(box)
				area = int(side * side) if side else 0
				alt = ""
				src = ""
				try:
					alt = (await el.get_attribute("alt")) or ""
					src = (await el.get_attribute("src")) or ""
				except Exception:
					pass
				blob = f"{alt} {src}".lower()
				qr_hint = any(
					k in blob for k in ("qr", "qrcode", "二维码", "weixin", "wxcode", "login", "code")
				)
				if not qr_hint:
					continue
				shot = await el.screenshot(type="png")
				if not shot or _is_icon_png(shot, side=side, area=area, from_img=True):
					continue
				rank = area + len(shot)
				if rank > best_rank:
					best = shot
					best_rank = rank
			except Exception:
				continue
	return best


async def inspect(page: Any) -> dict[str, Any]:
	merged = {
		"loggedIn": False,
		"scanned": False,
		"loginPage": False,
		"hasSend": False,
		"placeholder": False,
	}
	for data in await _eval_frames(page, _INSPECT_JS):
		if not isinstance(data, dict):
			continue
		if data.get("loggedIn"):
			return data
		if data.get("scanned"):
			merged["scanned"] = True
		if data.get("loginPage"):
			merged["loginPage"] = True
		if data.get("hasSend"):
			merged["hasSend"] = True
		if data.get("placeholder"):
			merged["placeholder"] = True
	if merged["hasSend"] or merged["placeholder"]:
		merged["loggedIn"] = True
	return merged


async def qr_expired(page: Any) -> bool:
	try:
		body = await page.inner_text("body")
		return "二维码失效" in body or "点击刷新" in body
	except Exception:
		return False


async def refresh_qr(page: Any) -> None:
	for name in ("点击刷新", "刷新"):
		loc = page.get_by_text(name, exact=False)
		try:
			if await loc.count() and await loc.first.is_visible():
				await loc.first.click()
				await page.wait_for_timeout(500)
				return
		except Exception:
			continue


async def read_chat_text(page: Any) -> str:
	chunks: list[str] = []
	for data in await _eval_frames(page, _READ_CHAT_JS):
		if isinstance(data, dict):
			t = str(data.get("text") or "").strip()
			if t:
				chunks.append(t)
	text = "\n".join(chunks)
	for snip in PLACEHOLDER_SNIPS:
		text = "\n".join(line for line in text.splitlines() if snip not in line)
	return text.strip()


async def install_chat_watch(page: Any, handler: Any) -> bool:
	try:
		await page.expose_function("xeyoInbound", handler)
	except Exception:
		pass
	try:
		ok = await page.evaluate(_WATCH_CHAT_JS)
		return bool(ok)
	except Exception:
		return False


async def _read_body_text(page: Any) -> str:
	chunks: list[str] = []
	for data in await _eval_frames(
		page,
		"() => (document.body && (document.body.innerText || '') || '').replace(/\\r/g, '')",
	):
		if data:
			chunks.append(str(data))
	return "\n".join(chunks).strip()


async def _composer_is_empty(page: Any) -> bool:
	for sel in ("textarea", "[contenteditable='true']", "[contenteditable='plaintext-only']"):
		found = await _lowest_visible(page, lambda ctx, s=sel: ctx.locator(s))
		if found is None:
			continue
		try:
			text = (await found.inner_text()) or ""
			if not text.strip():
				return True
		except Exception:
			continue
	return False


async def send_text(page: Any, text: str) -> None:
	if not (text or "").strip():
		return
	marker = _send_marker(text)
	await _fill_composer(page, text)
	clicked = await _click_send_trusted(page)
	if not clicked:
		await page.evaluate(_CLICK_SEND_JS)
	if await _wait_marker(page, marker, tries=4):
		return
	await page.keyboard.press("Enter")
	if await _wait_marker(page, marker, tries=3):
		return
	if await _composer_is_empty(page):
		return
	raise RuntimeError("wechat send not confirmed")


def _send_marker(text: str) -> str:
	t = " ".join((text or "").split())
	if len(t) <= 48:
		return t
	return t[-48:]


def _page_frames(page: Any) -> list[Any]:
	frames = list(getattr(page, "frames", None) or [])
	return frames if frames else [page]


async def _lowest_visible(page: Any, make_loc) -> Any | None:
	best = None
	best_y = -1.0
	for ctx in _page_frames(page):
		try:
			loc = make_loc(ctx)
			n = await loc.count()
		except Exception:
			continue
		for i in range(min(n, 10)):
			el = loc.nth(i)
			try:
				if not await el.is_visible():
					continue
				box = await el.bounding_box()
				if not box or box["height"] < 12:
					continue
				if box["y"] >= best_y:
					best_y = box["y"]
					best = el
			except Exception:
				continue
	return best


async def _fill_composer(page: Any, text: str) -> None:
	pid = id(page)
	cached = _COMPOSER_CACHE.get(pid)
	if cached is not None:
		try:
			if await cached.is_visible():
				await cached.click(timeout=1_200)
				try:
					await page.keyboard.press("Control+A")
					await page.keyboard.press("Backspace")
				except Exception:
					pass
				await page.keyboard.insert_text(text)
				return
		except Exception:
			_COMPOSER_CACHE.pop(pid, None)
	box = None
	for sel in ("textarea", "[contenteditable='true']", "[contenteditable='plaintext-only']"):
		found = await _lowest_visible(page, lambda ctx, s=sel: ctx.locator(s))
		if found is not None:
			box = found
			break
	if box is None:
		typed = False
		for ok in await _eval_frames(page, _TYPE_JS, text):
			if ok:
				typed = True
				break
		if not typed:
			raise RuntimeError("filehelper composer not found")
		return
	_COMPOSER_CACHE[pid] = box
	await box.click(timeout=2_500)
	try:
		await page.keyboard.press("Control+A")
		await page.keyboard.press("Backspace")
	except Exception:
		pass
	await page.keyboard.insert_text(text)


async def _click_send_trusted(page: Any) -> bool:
	pid = id(page)
	cached = _SEND_CACHE.get(pid)
	if cached is not None:
		try:
			if await cached.is_visible():
				await cached.click(timeout=900)
				return True
		except Exception:
			_SEND_CACHE.pop(pid, None)
	makers = (
		lambda ctx: ctx.get_by_role("button", name="发送"),
		lambda ctx: ctx.get_by_text("发送", exact=True),
		lambda ctx: ctx.get_by_text("Send", exact=True),
	)
	for make in makers:
		btn = await _lowest_visible(page, make)
		if btn is None:
			continue
		try:
			await btn.click(timeout=900)
			_SEND_CACHE[pid] = btn
			return True
		except Exception:
			try:
				await btn.click(timeout=500, force=True)
				_SEND_CACHE[pid] = btn
				return True
			except Exception:
				continue
	return False


async def _wait_marker(page: Any, marker: str, *, tries: int) -> bool:
	if not marker:
		return False
	folded = marker.replace("\n", " ")
	prefix = marker.split("\n", 1)[0].strip()
	for _ in range(tries):
		body = await _read_body_text(page)
		flat = " ".join(body.split())
		if marker in body or folded in flat:
			return True
		if prefix and prefix in body:
			return True
		await page.wait_for_timeout(80)
	return False


async def send_file(page: Any, path: Path) -> None:
	target = str(path.resolve())
	file_input = page.locator('input[type="file"]')
	if await file_input.count():
		await file_input.first.set_input_files(target)
		await page.wait_for_timeout(400)
		return
	async with page.expect_file_chooser(timeout=8_000) as chooser_info:
		await _click_attach(page)
	chooser = await chooser_info.value
	await chooser.set_files(target)
	await page.wait_for_timeout(400)


async def _click_attach(page: Any) -> None:
	candidates = [
		page.locator("input[type=file]"),
		page.get_by_role("button").nth(0),
		page.locator("svg").first,
	]
	for loc in candidates:
		try:
			if await loc.count():
				await loc.first.click()
				return
		except Exception:
			continue
	raise RuntimeError("filehelper attach control not found")


def chunk_text(text: str, size: int = 4000) -> list[str]:
	t = text or ""
	if len(t) <= size:
		return [t] if t else []
	return [t[i : i + size] for i in range(0, len(t), size)]
