"""xeyo sessions list|show|rm."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from cli import http_api
from cli.config_store import load_config, resolve_api_key, resolve_server_base_url

console = Console()


def _client(base_url: str | None, api_key: str | None):
	cfg = load_config()
	url = resolve_server_base_url(base_url, cfg=cfg)
	key = resolve_api_key(api_key, cfg=cfg)
	return http_api.make_client(url, key), url


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
	client, url = _client(base_url, api_key)
	try:
		sessions = http_api.list_sessions(client)
	except Exception as exc:  # noqa: BLE001
		console.print(
			f"[red]failed to list sessions via {url}: {exc}[/red]\n"
			f"[dim]Is the server up? Try: xeyo serve[/dim]"
		)
		return 1
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
			str(s.get("id") or ""),
			str(s.get("title") or ""),
			format_updated_at(s.get("updatedAt") or s.get("updated_at")),
		)
	if not sessions:
		console.print("[dim]no sessions on disk (or server unreachable)[/dim]")
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
	client, url = _client(base_url, api_key)
	try:
		data = http_api.get_messages(client, session_id)
	except Exception as exc:  # noqa: BLE001
		console.print(
			f"[red]failed to show {session_id} via {url}: {exc}[/red]\n"
			f"[dim]Is the server up? Try: xeyo serve[/dim]"
		)
		return 1
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
		console.print(f"[bold]{role}[/bold]: {snip}")
	return 0


def cmd_rm(
	session_id: str,
	*,
	base_url: str | None = None,
	api_key: str | None = None,
) -> int:
	client, url = _client(base_url, api_key)
	try:
		http_api.delete_session(client, session_id)
	except Exception as exc:  # noqa: BLE001
		console.print(f"[red]failed to delete {session_id} via {url}: {exc}[/red]")
		return 1
	finally:
		client.close()
	console.print(f"deleted {session_id}")
	return 0
