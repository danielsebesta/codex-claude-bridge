from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_ENV_FILENAME = ".claude-codex-bridge.env"


def default_env_candidates(cwd: Path | None = None) -> list[Path]:
    base = Path(cwd or Path.cwd())
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [
        base / DEFAULT_ENV_FILENAME,
        xdg_config_home / "claude-codex-bridge" / "config.env",
        Path.home() / ".config" / "claude-codex-bridge" / "config.env",
    ]


def resolve_env_file(explicit: str | None = None, cwd: Path | None = None) -> Path | None:
    requested = explicit or os.environ.get("CLAUDE_CODEX_BRIDGE_ENV_FILE")
    if requested:
        path = Path(requested).expanduser()
        return path if path.is_file() else None

    for candidate in default_env_candidates(cwd):
        if candidate.is_file():
            return candidate
    return None


def parse_env_lines(lines: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        parsed[key] = value
    return parsed


def load_env_file(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    return parse_env_lines(path.read_text(encoding="utf-8").splitlines())


def merged_env(explicit_env_file: str | None = None, cwd: Path | None = None) -> dict[str, str]:
    values = dict(os.environ)
    env_file = resolve_env_file(explicit_env_file, cwd)
    file_values = load_env_file(env_file)
    for key, value in file_values.items():
        values.setdefault(key, value)
    if env_file is not None:
        values["CLAUDE_CODEX_BRIDGE_ACTIVE_ENV_FILE"] = str(env_file)
    return values


def env_int(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_args(values: dict[str, str], key: str, default: str = "") -> list[str]:
    raw = values.get(key, default).strip()
    if not raw:
        return []
    return shlex.split(raw)


@dataclass(frozen=True)
class BridgeSettings:
    host: str
    port: int
    default_model: str
    vendor_name: str
    codex_bin: str
    codex_model: str | None
    codex_exec_args: tuple[str, ...]
    workdir: Path | None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_env(cls, values: dict[str, str]) -> "BridgeSettings":
        workdir = values.get("CCB_WORKDIR", "").strip()
        return cls(
            host=values.get("CCB_BRIDGE_HOST", "127.0.0.1"),
            port=env_int(values, "CCB_BRIDGE_PORT", 8787),
            default_model=values.get("CCB_MODEL_SONNET", "gpt-5.4"),
            vendor_name=values.get("CCB_VENDOR_NAME", "OpenAI"),
            codex_bin=values.get("CCB_CODEX_BIN", "codex"),
            codex_model=values.get("CCB_CODEX_MODEL", "").strip() or None,
            codex_exec_args=tuple(env_args(values, "CCB_CODEX_EXEC_ARGS", "--full-auto")),
            workdir=Path(workdir).expanduser().resolve() if workdir else None,
        )


@dataclass(frozen=True)
class LauncherSettings:
    bridge_url: str
    model_sonnet: str
    model_opus: str
    model_haiku: str
    model_custom: str | None
    custom_model_name: str
    launch_model: str
    claude_bin: str
    codex_bin: str

    @classmethod
    def from_env(cls, values: dict[str, str]) -> "LauncherSettings":
        host = values.get("CCB_BRIDGE_HOST", "127.0.0.1")
        port = env_int(values, "CCB_BRIDGE_PORT", 8787)
        return cls(
            bridge_url=values.get("CCB_BRIDGE_URL", f"http://{host}:{port}"),
            model_sonnet=values.get("CCB_MODEL_SONNET", "gpt-5.4"),
            model_opus=values.get("CCB_MODEL_OPUS", "gpt-5.3-codex"),
            model_haiku=values.get("CCB_MODEL_HAIKU", "gpt-5.4-mini"),
            model_custom=values.get("CCB_MODEL_CUSTOM", "").strip() or None,
            custom_model_name=values.get("CCB_CUSTOM_MODEL_NAME", "Custom OpenAI Model"),
            launch_model=values.get("CCB_LAUNCH_MODEL", "sonnet"),
            claude_bin=values.get("CCB_CLAUDE_BIN", "claude"),
            codex_bin=values.get("CCB_CODEX_BIN", "codex"),
        )
