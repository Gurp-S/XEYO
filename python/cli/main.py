"""Typer entry: `xeyo` / `python -m cli`."""

from __future__ import annotations

from typing import Optional

import typer

from cli import __version__

app = typer.Typer(
	name="xeyo",
	help="◆ XEYO — I am XEYO. Run with no args to open chat.",
	invoke_without_command=True,
	no_args_is_help=False,
	add_completion=False,
	rich_markup_mode="rich",
)

sessions_app = typer.Typer(help="Manage sessions via running HTTP server.")
config_app = typer.Typer(help="Read/write ~/.xeyo/config.toml")
coord_app = typer.Typer(help="Coord worker pool (feature-flag gated).")
app.add_typer(sessions_app, name="sessions")
app.add_typer(config_app, name="config")
app.add_typer(coord_app, name="coord")


def _run_chat(
	*,
	prompt: Optional[list[str]],
	cwd: Optional[str],
	session: Optional[str],
	provider: Optional[str],
	model: Optional[str],
	api_key: Optional[str],
	base_url: Optional[str],
	permission_mode: Optional[str],
	agent_mode: str,
	print_mode: bool,
	json_mode: bool,
	profile: Optional[str],
) -> None:
	from cli.chat_cmd import run_chat
	from cli.config_store import (
		load_config,
		resolve_api_key,
		resolve_base_url,
		resolve_model,
		resolve_permission_mode,
		resolve_provider,
	)
	from cli.setup_wizard import ensure_ready_for_chat

	cfg = load_config(profile=profile)
	prov = resolve_provider(provider, cfg=cfg)
	key = resolve_api_key(api_key, cfg=cfg)
	url = resolve_base_url(base_url, cfg=cfg)
	ensure_ready_for_chat(
		provider=prov,
		api_key=key,
		base_url=url,
		json_mode=json_mode,
		print_mode=print_mode,
	)
	# 在向导可能写入之后重新加载。
	cfg = load_config(profile=profile)
	prov = resolve_provider(provider, cfg=cfg)
	key = resolve_api_key(api_key, cfg=cfg)
	url = resolve_base_url(base_url, cfg=cfg)
	text = " ".join(prompt).strip() if prompt else ""
	code = run_chat(
		prompt=text or None,
		cwd=cwd,
		session_id=session,
		provider=prov,
		model=resolve_model(model, cfg=cfg),
		api_key=key,
		base_url=url,
		permission_mode=resolve_permission_mode(permission_mode, cfg=cfg),
		agent_mode=agent_mode,
		print_mode=print_mode,
		json_mode=json_mode,
	)
	raise typer.Exit(code)


@app.callback(invoke_without_command=True)
def root(
	ctx: typer.Context,
	cwd: Optional[str] = typer.Option(None, "--cwd", help="Workspace directory"),
	session: Optional[str] = typer.Option(None, "--session", "-s"),
	provider: Optional[str] = typer.Option(None, "--provider"),
	model: Optional[str] = typer.Option(None, "--model", "-m"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	permission_mode: Optional[str] = typer.Option(None, "--permission-mode"),
	agent_mode: str = typer.Option("agent", "--agent-mode"),
	print_mode: bool = typer.Option(False, "--print"),
	json_mode: bool = typer.Option(False, "--json"),
	profile: Optional[str] = typer.Option(
		None, "--profile", help="Select a [profiles.<name>] override"
	),
) -> None:
	"""Bare `xeyo` opens an in-process chat REPL (same as `xeyo chat`)."""
	if ctx.invoked_subcommand is not None:
		return
	_run_chat(
		prompt=None,
		cwd=cwd,
		session=session,
		provider=provider,
		model=model,
		api_key=api_key,
		base_url=base_url,
		permission_mode=permission_mode,
		agent_mode=agent_mode,
		print_mode=print_mode,
		json_mode=json_mode,
		profile=profile,
	)


@app.command("version")
def version_cmd() -> None:
	typer.echo(__version__)


@app.command("setup")
def setup_cmd() -> None:
	"""Interactive first-run config (provider, API key, default workspace)."""
	from cli.setup_wizard import run_setup_wizard

	run_setup_wizard(force=True)


@app.command("chat")
def chat_cmd(
	prompt: Optional[list[str]] = typer.Argument(None, help="Optional one-shot prompt"),
	cwd: Optional[str] = typer.Option(None, "--cwd"),
	session: Optional[str] = typer.Option(None, "--session", "-s"),
	provider: Optional[str] = typer.Option(None, "--provider"),
	model: Optional[str] = typer.Option(None, "--model", "-m"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	permission_mode: Optional[str] = typer.Option(None, "--permission-mode"),
	agent_mode: str = typer.Option("agent", "--agent-mode"),
	print_mode: bool = typer.Option(False, "--print"),
	json_mode: bool = typer.Option(False, "--json"),
	profile: Optional[str] = typer.Option(
		None, "--profile", help="Select a [profiles.<name>] override"
	),
) -> None:
	"""In-process chat REPL (or one-shot with prompt / --print)."""
	_run_chat(
		prompt=prompt,
		cwd=cwd,
		session=session,
		provider=provider,
		model=model,
		api_key=api_key,
		base_url=base_url,
		permission_mode=permission_mode,
		agent_mode=agent_mode,
		print_mode=print_mode,
		json_mode=json_mode,
		profile=profile,
	)


@app.command("attach")
def attach_cmd(
	session_id: str = typer.Argument(...),
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	provider: Optional[str] = typer.Option(None, "--provider"),
	model: Optional[str] = typer.Option(None, "--model", "-m"),
	cwd: Optional[str] = typer.Option(None, "--cwd"),
	permission_mode: Optional[str] = typer.Option(None, "--permission-mode"),
	agent_mode: str = typer.Option("agent", "--agent-mode"),
	json_mode: bool = typer.Option(False, "--json"),
) -> None:
	from cli.attach_cmd import attach_repl

	raise typer.Exit(
		attach_repl(
			session_id,
			base_url=base_url,
			api_key=api_key,
			provider=provider,
			model=model,
			cwd=cwd,
			permission_mode=permission_mode,
			agent_mode=agent_mode,
			json_mode=json_mode,
		)
	)


@app.command("serve")
def serve_cmd(
	host: Optional[str] = typer.Option(None, "--host"),
	port: Optional[int] = typer.Option(None, "--port"),
	cwd: Optional[str] = typer.Option(None, "--cwd"),
) -> None:
	from cli.serve_cmd import run_serve

	run_serve(host=host, port=port, cwd=cwd)


@coord_app.command("run")
def coord_run(
	cwd: Optional[str] = typer.Option(None, "--cwd"),
	provider: Optional[str] = typer.Option(None, "--provider"),
	model: Optional[str] = typer.Option(None, "--model", "-m"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	idle_poll_sec: float = typer.Option(2.0, "--idle-poll"),
	max_tasks: int = typer.Option(0, "--tasks", help="处理 N 张任务卡后退出(0=不限)"),
	once: bool = typer.Option(False, "--once"),
	reconcile_only: bool = typer.Option(False, "--reconcile-only"),
) -> None:
	from cli.coord_cmd import run_coord_run

	run_coord_run(
		cwd=cwd, provider=provider, model=model, api_key=api_key,
		idle_poll_sec=idle_poll_sec, max_tasks=max_tasks, once=once,
		reconcile_only=reconcile_only,
	)


@coord_app.command("status")
def coord_status(
	cwd: Optional[str] = typer.Option(None, "--cwd"),
	as_json: bool = typer.Option(False, "--json"),
) -> None:
	from cli.coord_cmd import run_coord_status

	run_coord_status(cwd=cwd, as_json=as_json)


@sessions_app.command("list")
def sessions_list(
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	as_json: bool = typer.Option(False, "--json"),
) -> None:
	from cli.sessions_cmd import cmd_list

	raise typer.Exit(cmd_list(base_url=base_url, api_key=api_key, as_json=as_json))


@sessions_app.command("show")
def sessions_show(
	session_id: str = typer.Argument(...),
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
	as_json: bool = typer.Option(False, "--json"),
	limit: int = typer.Option(20, "--limit"),
) -> None:
	from cli.sessions_cmd import cmd_show

	raise typer.Exit(
		cmd_show(
			session_id,
			base_url=base_url,
			api_key=api_key,
			as_json=as_json,
			limit=limit,
		)
	)


@sessions_app.command("rm")
def sessions_rm(
	session_id: str = typer.Argument(...),
	base_url: Optional[str] = typer.Option(None, "--base-url"),
	api_key: Optional[str] = typer.Option(None, "--api-key"),
) -> None:
	from cli.sessions_cmd import cmd_rm

	raise typer.Exit(cmd_rm(session_id, base_url=base_url, api_key=api_key))


@config_app.command("path")
def config_path_cmd() -> None:
	from cli.config_store import config_path

	typer.echo(str(config_path()))


@config_app.command("show")
def config_show_cmd() -> None:
	from cli.config_store import asdict_safe, load_config

	for k, v in asdict_safe(load_config()).items():
		display = v
		if k == "api_key" and v:
			display = v[:4] + "…" + v[-2:] if len(v) > 8 else "***"
		typer.echo(f"{k}={display}")


@config_app.command("set")
def config_set_cmd(
	key: str = typer.Argument(...),
	value: str = typer.Argument(...),
) -> None:
	from dataclasses import fields

	from cli.config_store import load_config, save_config, validate_config_value

	cfg = load_config()
	known = {f.name for f in fields(cfg)}
	if key not in known:
		typer.echo(f"unknown key {key}; known: {', '.join(sorted(known))}", err=True)
		raise typer.Exit(2)
	try:
		normalized = validate_config_value(key, value)
	except ValueError as exc:
		typer.echo(str(exc), err=True)
		raise typer.Exit(2) from exc
	setattr(cfg, key, normalized)
	typer.echo(f"wrote {save_config(cfg)}")


if __name__ == "__main__":
	app()
