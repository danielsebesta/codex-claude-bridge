from __future__ import annotations

import argparse
import shutil
import stat
import sys
from pathlib import Path


WRAPPER = """#!/usr/bin/env bash
exec claude-codex "$@"
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a shim so `claude` invokes `claude-codex`.")
    parser.add_argument("--target", default="~/.local/bin/claude", help="Shim path to write")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing non-shim file")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which("claude-codex") is None:
        print("Missing `claude-codex` in PATH. Install the package first.", file=sys.stderr)
        return 1

    if target.exists():
        current = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        if current == WRAPPER:
            print(f"Shim already installed at {target}")
            return 0
        if not args.force:
            print(f"Refusing to overwrite existing file: {target}. Re-run with --force if that is intentional.", file=sys.stderr)
            return 1

    target.write_text(WRAPPER, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed shim at {target}")
    print("Make sure this directory appears before the real Claude binary in PATH.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
