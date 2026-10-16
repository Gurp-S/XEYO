"""Install a wheel outside the checkout and exercise its declared dependency sets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--product", action="store_true")
    parser.add_argument("--index-url", help="Explicit package index for this isolated verification")
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    checkout = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for name in ("xeyo/__init__.py", "coord/__init__.py", "lsp/__init__.py",
                     "sidecar/policy.py", "model/reference_v41/tokenizer.json"):
            assert name in names, f"wheel missing {name}"
        assert not any(name.startswith(("evals/", "tests/")) for name in names)
    with tempfile.TemporaryDirectory(prefix="xeyo-wheel-check-") as temporary:
        root = Path(temporary)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        environment = {**os.environ, "PYTHONUTF8": "1"}
        def execute(*command):
            result = subprocess.run([str(python), *map(str, command)], cwd=root,
                                    env=environment, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout
        index = ["--index-url", args.index_url] if args.index_url else []
        execute("-m", "pip", "install", "--disable-pip-version-check", *index, wheel)
        engine = json.loads(execute("-I", checkout / "python/scripts/check_engine_install.py"))
        result = {"wheel": wheel.name, "engine": engine}
        if args.product:
            execute("-m", "pip", "install", "--disable-pip-version-check", *index, str(wheel) + "[product]")
            result["product"] = json.loads(execute("-I", checkout / "python/scripts/check_product_install.py"))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
