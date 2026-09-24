"""xeyo sessions list|show|rm."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from cli import http_api
from cli.config_store import load_config, resolve_api_key, resolve_server_base_url
from cli.cwdutil import ensure_utf8_stdio

console = Console()


def _client(base_url: str | None, api_key: str | None):
	cfg = load_config()
	url = resolve_server_base_url(base_url, cfg=cfg)
	key = resolve_api_key(api_key, cfg=cfg)
	return http_api.make_client(url, key), url


def _check_path_id(session_id: str) -> int | None:
	"""把 ``PathIdError`` 变成用法退出码 2（不是「操作失败」的 1）。"""
	try:
		http_api.require_path_segment(session_id)
	except http_api.PathIdError as exc:
		console.print(
			f"[red]{escape(str(exc))}[/red] "
			"[dim](a session id goes into the URL path: only letters, digits, "
			"dot, underscore, colon, dash; max 128)[/dim]"
		)
		return 2
	return None


def _unreachable(what: str, url: str, exc: Exception) -> int:
	"""转述服务端自己给的原因；只有连不上时才提示起服务。"""
	if isinstance(exc, http_api.ApiError):
		console.print(
			f"[red]{escape(what)} failed via {escape(url)}: "
			f"{escape(exc.detail or f'HTTP {exc.status}')}[/red]"
		)
		return 1
	console.print(
		f"[red]{escape(what)} failed via {escape(url)}: {escape(str(exc))}[/red]\n"
		"[dim]Is the server up? Try: xeyo serve[/dim]"
	)
	return 1


def format_updated_at(raw: object) -> str:
	"""Turn ms epoch (or ISO) into a short local/relative string."""
	if raw is None or raw == "":
		return ""
	try:
		ms = int(raw)
	except (TypeError, ValueError):
		return str(raw)
	if ms > 10_000_000_000:
		# 单位：毫秒
		ts = ms / 1000.0
	else:
		ts = float(ms)
	try:
		dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
	except (OverflowError, OSError, ValueError):
		return str(raw)
	delta = time.time() - ts
	if delta < 60:
		rel = "just now"
	elif delta < 3600:
		rel = f"{int(delta // 60)}m ago"
	elif delta < 86400:
		rel = f"{int(delta // 3600)}h ago"
	elif delta < 86400 * 14:
		rel = f"{int(delta // 86400)}d ago"
	else:
		rel = dt.strftime("%Y-%m-%d")
	return f"{rel} ({dt.strftime('%m-%d %H:%M')})"


def cmd_list(*, base_url: str | None = None, api_key: str | None = None, as_json: bool = False) -> int:
	ensure_utf8_stdio()
	client, url = _client(base_url, api_key)
	try:
		sessions = http_api.list_sessions(client)
	except Exception as exc:  # noqa: BLE001
		return _unreachable("list sessions", url, exc)
	finally:
		client.close()
	if as_json:
		print(json.dumps(sessions, ensure_ascii=False, indent=2))
		return 0
	from cli import ui as cli_ui

	table = Table(title=cli_ui.brand_mark(), border_style=cli_ui.ACCENT)
	table.add_column("id", style="bold")
	table.add_column("title")
	table.add_column("updated", style="dim")
	for s in sessions:
		if not isinstance(s, dict):
			continue
		table.add_row(
			# 标题与 id 是用户/模型写的文本：不转义就是一个方括号让整条命令
			# 抛 MarkupError（把数据打印成数据，不是打印成样式）。
			escape(str(s.get("id") or "")),
			escape(str(s.get("title") or "")),
			format_updated_at(s.get("updatedAt") or s.get("updated_at")),
		)
	if not sessions:
		console.print("[dim]server reported no sessions[/dim]")
	else:
		console.print(table)
	return 0


def cmd_show(
	session_id: str,
	*,
	base_url: str | None = None,
	api_key: str | None = None,
	as_json: bool = False,
	limit: int = 20,
) -> int:
	ensure_utf8_stdio()
	bad = _check_path_id(session_id)
	if bad is not None:
		return bad
	if limit < 0:
		console.print(
			"[red]--limit must be 0 (all messages) or positive[/red]"
		)
		return 2
	client, url = _client(base_url, api_key)
	try:
		data = http_api.get_messages(client, session_id)
	except Exception as exc:  # noqa: BLE001
		return _unreachable(f"show {session_id}", url, exc)
	finally:
		client.close()
	if as_json:
		print(json.dumps(data, ensure_ascii=False, indent=2))
		return 0
	messages = data.get("messages") if isinstance(data, dict) else []
	msgs = list(messages or [])
	tail = msgs[-limit:] if limit > 0 else msgs
	console.print(f"[dim]session={session_id} showing last {len(tail)}/{len(msgs)}[/dim]")
	for m in tail:
		if not isinstance(m, dict):
			continue
		role = str(m.get("role") or "?")
		content = m.get("content")
		text = json.dumps(content, ensure_ascii=False) if isinstance(content, list) else str(content or "")
		snip = text if len(text) <= 240 else text[:237] + "..."
		console.print(f"[bold]{escape(role)}[/bold]: {escape(snip)}")
	return 0


def cmd_rm(
	session_id: str,
	*,
	base_url: str | None = None,
	api_key: str | None = None,
) -> int:
	ensure_utf8_stdio()
	bad = _check_path_id(session_id)
	if bad is not None:
		return bad
	client, url = _client(base_url, api_key)
	try:
		result = http_api.delete_session(client, session_id)
	except Exception as exc:  # noqa: BLE001
		return _unreachable(f"delete {session_id}", url, exc)
	finally:
		client.close()
	# 「200 且服务端说没删干净」必须进收据：否则用户以为数据没了。
	if result.get("ok") is not True:
		reason = result.get("detail") or result.get("error") or result.get("reason") or ""
		console.print(
			f"[red]delete {session_id} was not confirmed by the server[/red]"
			+ (f": {escape(str(reason))}" if reason else "")
		)
		return 1
	errs = result.get("removal_errors")
	if isinstance(errs, list) and errs:
		console.print(
			f"[yellow]deleted {session_id}, but the server reported "
			f"{len(errs)} cleanup failure(s): {escape(json.dumps(errs, ensure_ascii=False)[:400])}[/yellow]"
		)
		return 1
	removed = result.get("removed")
	# 服务端没给 removed 列表时不说「removed 0」——没记录 ≠ 零个文件。
	note = f" (removed {len(removed)} file(s))" if isinstance(removed, list) else ""
	console.print(f"deleted {session_id}{note}")
	return 0
