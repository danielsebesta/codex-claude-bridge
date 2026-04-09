from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import BridgeSettings, merged_env


SERVER_VERSION = "codex-claude-bridge/0.1"


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text", "")))
            elif block_type == "tool_result":
                tool_name = block.get("tool_use_id", "tool")
                parts.append(f"[tool_result:{tool_name}]\n{json.dumps(block.get('content', ''), ensure_ascii=False)}")
            elif block_type == "tool_use":
                tool_name = block.get("name", "tool")
                parts.append(f"[tool_use:{tool_name}]\n{json.dumps(block.get('input', {}), ensure_ascii=False)}")
            elif block_type == "image":
                parts.append("[image omitted]")
            elif block_type == "document":
                parts.append("[document omitted]")
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(part for part in parts if part)
    return str(value)


def render_system(system: Any) -> str:
    text = coerce_text(system).strip()
    if not text:
        return ""
    return f"<system>\n{text}\n</system>\n\n"


def render_messages(messages: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = coerce_text(message.get("content")).strip()
        if content:
            rendered.append(f"<{role}>\n{content}\n</{role}>")
    return "\n\n".join(rendered)


def build_prompt(payload: dict[str, Any], settings: BridgeSettings) -> str:
    system = render_system(payload.get("system"))
    messages = render_messages(payload.get("messages", []))
    tool_count = len(payload.get("tools", []) or [])
    requested_model = str(payload.get("model") or settings.default_model)
    tool_notice = ""
    if tool_count:
        tool_notice = (
            "\n\n<bridge_notice>\n"
            f"The upstream client sent {tool_count} Claude tool definitions. "
            "This bridge does not emulate Claude tool-use blocks. "
            "You may use Codex's own tools if needed, then return a plain-text assistant reply.\n"
            "</bridge_notice>"
        )

    instructions = (
        f"You are {requested_model} by {settings.vendor_name}, running through Codex CLI behind an Anthropic-compatible shim.\n"
        "Treat the transcript below as the full conversation context.\n"
        "Return only the next assistant reply as plain text.\n"
        f"If asked about your identity, model, or vendor, answer truthfully: {requested_model} by {settings.vendor_name} via Codex CLI bridge.\n"
        "Do not claim to be Claude, Sonnet, or Anthropic.\n"
        "Do not mention the bridge unless it is directly relevant.\n"
    )
    return f"{instructions}\n{system}{messages}{tool_notice}\n"


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def message_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def run_codex(prompt: str, settings: BridgeSettings, cwd: Path) -> tuple[str, list[str], int, int | None, int | None]:
    command = [
        settings.codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
    ]
    if settings.codex_model:
        command.extend(["--model", settings.codex_model])
    command.extend(settings.codex_exec_args)
    command.append(prompt)

    result = subprocess.run(
        command,
        cwd=str(settings.workdir or cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    text_parts: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("{"):
            stderr_lines.append(stripped)
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            stderr_lines.append(stripped)
            continue

        event_type = event.get("type")
        if event_type == "agent_message_delta":
            delta = event.get("delta") or {}
            text = delta.get("text")
            if text:
                text_parts.append(str(text))
        elif event_type == "agent_message":
            message = event.get("message") or {}
            content = message.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "output_text":
                        text_parts.append(str(item.get("text", "")))
            elif isinstance(content, str):
                text_parts.append(content)
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                text = item.get("text")
                if text:
                    text_parts.append(str(text))
        elif event_type == "error":
            message = event.get("message")
            if message:
                stderr_lines.append(str(message))
        elif event_type == "turn.completed":
            usage = event.get("usage") or {}
            if isinstance(usage.get("input_tokens"), int):
                input_tokens = usage["input_tokens"]
            if isinstance(usage.get("output_tokens"), int):
                output_tokens = usage["output_tokens"]

    text = "".join(text_parts).strip()
    if not text:
        text = "Codex returned no assistant text."
        if stderr_lines:
            text += "\n\nBridge diagnostics:\n" + "\n".join(stderr_lines[-10:])

    return text, stderr_lines, result.returncode, input_tokens, output_tokens


def message_response(model: str, text: str, input_tokens: int, output_tokens: int, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": message_id(),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


class BridgeServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], request_handler_class: type[BaseHTTPRequestHandler], settings: BridgeSettings, cwd: Path) -> None:
        super().__init__(server_address, request_handler_class)
        self.settings = settings
        self.cwd = cwd


class RequestHandler(BaseHTTPRequestHandler):
    server_version = SERVER_VERSION
    protocol_version = "HTTP/1.1"

    @property
    def bridge_server(self) -> BridgeServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("request-id", request_id())
        self.end_headers()
        self.wfile.write(body)

    def _send_head_only(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.send_header("request-id", request_id())
        self.end_headers()

    def _send_sse(self, event_type: str, payload: dict[str, Any]) -> None:
        self.wfile.write(f"event: {event_type}\n".encode("utf-8"))
        self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send_error(self, status: int, message: str, error_type: str = "invalid_request_error") -> None:
        self._send_json(status, {"type": "error", "error": {"type": error_type, "message": message}})

    def _read_json(self) -> dict[str, Any] | None:
        length_raw = self.headers.get("Content-Length")
        if not length_raw:
            self._send_error(HTTPStatus.LENGTH_REQUIRED, "Missing Content-Length header")
            return None

        try:
            length = int(length_raw)
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header")
            return None

        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_error(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON")
            return None

    def do_HEAD(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/health", "/healthz"}:
            self._send_head_only(HTTPStatus.OK)
            return
        self._send_head_only(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/health", "/healthz"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "codex-claude-bridge",
                    "cwd": str(self.bridge_server.settings.workdir or self.bridge_server.cwd),
                    "default_model": self.bridge_server.settings.default_model,
                },
            )
            return
        self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {path}", "not_found_error")

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/v1/messages/count_tokens":
            payload = self._read_json()
            if payload is None:
                return
            prompt = build_prompt(payload, self.bridge_server.settings)
            self._send_json(HTTPStatus.OK, {"input_tokens": estimate_tokens(prompt)})
            return

        if path != "/v1/messages":
            self._send_error(HTTPStatus.NOT_FOUND, f"Unknown path: {path}", "not_found_error")
            return

        payload = self._read_json()
        if payload is None:
            return

        prompt = build_prompt(payload, self.bridge_server.settings)
        input_tokens = estimate_tokens(prompt)
        text, stderr_lines, return_code, real_input_tokens, real_output_tokens = run_codex(
            prompt,
            self.bridge_server.settings,
            self.bridge_server.cwd,
        )

        if real_input_tokens is not None:
            input_tokens = real_input_tokens
        output_tokens = real_output_tokens if real_output_tokens is not None else estimate_tokens(text)
        stop_reason = "end_turn"
        model = str(payload.get("model") or self.bridge_server.settings.default_model)

        if payload.get("stream"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("request-id", request_id())
            self.end_headers()

            start = message_response(model, "", input_tokens, 0, stop_reason=None)
            start["stop_reason"] = None
            self._send_sse("message_start", {"type": "message_start", "message": start})
            self._send_sse(
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            )
            chunk_size = 400
            for index in range(0, len(text), chunk_size):
                chunk = text[index:index + chunk_size]
                self._send_sse(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": chunk}},
                )
            self._send_sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            self._send_sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": output_tokens},
                },
            )
            self._send_sse("message_stop", {"type": "message_stop"})
            self.close_connection = True
            return

        response = message_response(model, text, input_tokens, output_tokens, stop_reason=stop_reason)
        if return_code != 0 and stderr_lines:
            response["bridge_diagnostics"] = stderr_lines[-10:]
        self._send_json(HTTPStatus.OK, response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local Anthropic-compatible bridge backed by Codex CLI.")
    parser.add_argument("--env-file", help="Optional config.env path")
    parser.add_argument("--host", help="Override bridge host")
    parser.add_argument("--port", type=int, help="Override bridge port")
    args = parser.parse_args(argv)

    env = merged_env(args.env_file)
    settings = BridgeSettings.from_env(env)
    if args.host:
        settings = BridgeSettings(
            host=args.host,
            port=settings.port,
            default_model=settings.default_model,
            vendor_name=settings.vendor_name,
            codex_bin=settings.codex_bin,
            codex_model=settings.codex_model,
            codex_exec_args=settings.codex_exec_args,
            workdir=settings.workdir,
        )
    if args.port:
        settings = BridgeSettings(
            host=settings.host,
            port=args.port,
            default_model=settings.default_model,
            vendor_name=settings.vendor_name,
            codex_bin=settings.codex_bin,
            codex_model=settings.codex_model,
            codex_exec_args=settings.codex_exec_args,
            workdir=settings.workdir,
        )

    if shutil.which(settings.codex_bin) is None:
        print(f"Missing Codex CLI binary: {settings.codex_bin}", file=sys.stderr)
        return 1

    server = BridgeServer((settings.host, settings.port), RequestHandler, settings, Path.cwd())
    print(f"codex-claude-bridge listening on {settings.base_url}", flush=True)
    print(f"codex working directory: {settings.workdir or Path.cwd()}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
