from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from .config import LauncherSettings, merged_env


def codex_logged_in(codex_bin: str) -> bool:
    result = subprocess.run(
        [codex_bin, "login", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def has_model_argument(args: list[str]) -> bool:
    for index, value in enumerate(args):
        if value == "--model":
            return True
        if value.startswith("--model="):
            return True
        if value == "-m" and index + 1 < len(args):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file")
    parser.add_argument("--help", action="store_true")
    known, passthrough = parser.parse_known_args(argv)

    if known.help:
        print("Usage: claude-codex [--env-file PATH] [claude args...]")
        return 0

    env = merged_env(known.env_file)
    settings = LauncherSettings.from_env(env)

    if shutil.which(settings.claude_bin) is None:
        print(f"Missing Claude CLI binary: {settings.claude_bin}", file=sys.stderr)
        return 1

    if shutil.which(settings.codex_bin) is None:
        print(f"Missing Codex CLI binary: {settings.codex_bin}", file=sys.stderr)
        return 1

    if not codex_logged_in(settings.codex_bin):
        print("Codex is not logged in. Run `codex login` first.", file=sys.stderr)
        return 1

    child_env = dict(os.environ)
    child_env.update(env)
    child_env["ANTHROPIC_BASE_URL"] = settings.bridge_url
    child_env["ANTHROPIC_API_KEY"] = child_env.get("ANTHROPIC_API_KEY", "claude-codex-bridge-local")
    child_env.pop("ANTHROPIC_AUTH_TOKEN", None)
    child_env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = settings.model_sonnet
    child_env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = settings.model_opus
    child_env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = settings.model_haiku
    child_env["CLAUDE_CODE_SUBAGENT_MODEL"] = settings.model_haiku
    if settings.model_custom:
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION"] = settings.model_custom
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION_NAME"] = settings.custom_model_name
        child_env["ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION"] = (
            f"Local Codex-backed bridge exposed to Claude Code as {settings.model_custom}"
        )
    else:
        child_env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION", None)
        child_env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION_NAME", None)
        child_env.pop("ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION", None)

    command = [settings.claude_bin, "--bare"]
    if not has_model_argument(passthrough):
        command.extend(["--model", settings.launch_model])
    command.extend(passthrough)

    os.execvpe(settings.claude_bin, command, child_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
