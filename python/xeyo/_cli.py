"""Optional product command, keeping a useful error for engine-only installs."""
def main() -> None:
    try:
        from cli.main import app
    except ModuleNotFoundError as exc:
        if exc.name not in {"typer", "rich"}:
            raise
        raise SystemExit('CLI dependencies are absent. Install "xeyo[cli]".') from None
    app()
