"""First-run / click-to-use onboarding for the CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cli import ui
from cli.config_store import (
	VALID_PROVIDERS,
	CliConfig,
	load_config,
	resolve_api_key,
	resolve_base_url,
	resolve_provider,
	save_config,
)


def needs_credentials(
	*,
	provider: str,
	api_key: str,
	base_url: str = "",
) -> bool:
	"""True when chat would likely fail without an interactive setup."""
	prov = (provider or "").strip().lower()
	if prov == "fake":
		return False
	if (api_key or "").strip():
		return False
	# Local OpenAI-compatible servers often need no key.
	if prov == "local" and (base_url or "").strip():
		return False
	return True


def _ask(label: str, *, default: str = "", password: bool = False) -> str:
	try:
		from rich.prompt import Prompt

		kwargs: dict = {"default": default, "console": ui.out}
		if password:
			kwargs["password"] = True
		return str(Prompt.ask(label, **kwargs) or "").strip()
	except Exception:
		suffix = f" [{default}]" if default else ""
		ui.out.print(f"{label}{suffix}: ", end="")
		return input().strip() or default


def _ask_choice(label: str, choices: list[str], *, default: str) -> str:
	try:
		from rich.prompt import Prompt

		return (
			Prompt.ask(label, choices=choices, default=default, console=ui.out)
			.strip()
			.lower()
		)
	except Exception:
		ui.out.print(f"{label} ({'/'.join(choices)}) [{default}]: ", end="")
		raw = input().strip().lower()
		return raw if raw in choices else default


def run_setup_wizard(
	*,
	cfg: CliConfig | None = None,
	force: bool = False,
) -> CliConfig:
	"""Interactive provider / key / workspace. Saves ~/.xeyo/config.toml."""
	cfg = cfg or load_config()
	provider = resolve_provider(None, cfg=cfg)
	api_key = resolve_api_key(None, cfg=cfg)
	base_url = resolve_base_url(None, cfg=cfg)

	if not force and not needs_credentials(
		provider=provider, api_key=api_key, base_url=base_url
	):
		return cfg

	ui.out.print()
	from cli.logo import logo_with_identity

	ui.out.print(logo_with_identity(accent=ui.ACCENT, muted=ui.MUTED))
	ui.out.print()
	ui.out.print(
		"[dim]Saved to ~/.xeyo/config.toml — re-run anytime with `xeyo setup`[/dim]"
	)
	ui.out.print()

	choices = sorted(VALID_PROVIDERS - {"fake"})
	prov_default = provider if provider in choices else "deepseek"
	cfg.provider = _ask_choice("Provider", choices, default=prov_default)

	if cfg.provider == "local":
		cfg.base_url = _ask(
			"Local base URL", default=base_url or "http://127.0.0.1:8080/v1"
		)
		key = _ask("API key (optional)", default=api_key or "", password=True)
		if key:
			cfg.api_key = key
	else:
		key = _ask("API key", default=api_key or "", password=True)
		if key:
			cfg.api_key = key
		elif not force:
			ui.err.print(
				"[bold yellow]No API key yet[/bold yellow] — "
				"set later: [bold]xeyo config set api_key …[/bold]"
			)

	model = _ask("Model (optional)", default=(cfg.model or "").strip())
	if model:
		cfg.model = model

	cwd_default = (cfg.last_cwd or "").strip() or os.getcwd()
	ws = _ask("Default workspace", default=cwd_default)
	if ws:
		from cli.cwdutil import try_resolve_workspace

		resolved = try_resolve_workspace(ws)
		if resolved:
			cfg.last_cwd = resolved
		else:
			p = Path(ws).expanduser()
			if p.is_dir():
				cfg.last_cwd = str(p.resolve())

	path = save_config(cfg)
	ui.out.print()
	ui.out.print(f"[bold {ui.OK}]✓[/bold {ui.OK}] saved [dim]{path}[/dim]")
	ui.out.print()
	return cfg


def ensure_ready_for_chat(
	*,
	provider: str,
	api_key: str,
	base_url: str,
	json_mode: bool,
	print_mode: bool,
) -> CliConfig:
	"""Run setup wizard when credentials are missing and stdin is a TTY."""
	cfg = load_config()
	if json_mode or print_mode:
		return cfg
	if not needs_credentials(provider=provider, api_key=api_key, base_url=base_url):
		return cfg
	if not sys.stdin.isatty():
		ui.err.print(
			"[bold red]No API key configured.[/bold red] "
			"Run [bold]xeyo setup[/bold] or "
			"[bold]xeyo config set api_key YOUR_KEY[/bold]"
		)
		raise SystemExit(2)
	return run_setup_wizard(cfg=cfg, force=True)
