# claude-codex-bridge

`claude-codex-bridge` is an experimental compatibility layer that lets the `claude` CLI talk to a local Anthropic-style endpoint backed by `codex exec`.

It exists for one narrow use case: you want the Claude Code client experience, but you want responses to come from your logged-in Codex CLI session instead of Anthropic's hosted models.

## Status

- Works as a proof of concept
- Public-ready codebase with no hardcoded user paths
- Still limited by Claude Code's private client behavior and model validation

This project is not affiliated with Anthropic or OpenAI.

## How it works

1. `codex-claude-bridge` starts a local HTTP server that implements a small subset of the Anthropic Messages API.
2. Each `/v1/messages` request is converted into a `codex exec --json` run.
3. `claude-codex` launches the `claude` CLI in `--bare` mode and points it at the local bridge.

## What this gives you

- Reuse your existing `codex login` session
- No OpenAI API key required
- Keep the Claude Code terminal client and slash-command UX

## Current limitations

- This is not a full Anthropic API implementation
- Each Claude request becomes a fresh Codex session
- Claude-native tool-use blocks are not emulated
- Claude Code may still show Claude product branding in parts of the UI
- Some Claude Code versions validate model names aggressively, so launch compatibility may require using a Claude alias internally while the bridge identifies itself publicly with your configured OpenAI model names

## Requirements

- Python 3.11+
- `claude` CLI installed
- `codex` CLI installed
- Successful `codex login`

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Configuration

The launcher and bridge load environment variables from the first file they find in this order:

1. `CLAUDE_CODEX_BRIDGE_ENV_FILE`
2. `./.claude-codex-bridge.env`
3. `$XDG_CONFIG_HOME/claude-codex-bridge/config.env`
4. `~/.config/claude-codex-bridge/config.env`

Start with:

```bash
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/claude-codex-bridge"
cp config.env.example "${XDG_CONFIG_HOME:-$HOME/.config}/claude-codex-bridge/config.env"
```

Key settings:

- `CCB_BRIDGE_HOST` and `CCB_BRIDGE_PORT`: local HTTP listener
- `CCB_MODEL_SONNET`, `CCB_MODEL_OPUS`, `CCB_MODEL_HAIKU`, `CCB_MODEL_CUSTOM`: model strings exposed through Claude Code slots
- `CCB_LAUNCH_MODEL`: model string passed to the `claude` client
- `CCB_CODEX_MODEL`: optional explicit Codex model override
- `CCB_CODEX_EXEC_ARGS`: extra flags appended to `codex exec`
- `CCB_WORKDIR`: optional fixed working directory for Codex execution

## Usage

Start the bridge in the repository where you want Codex to work:

```bash
codex-claude-bridge
```

Open another terminal and launch Claude Code against it:

```bash
claude-codex
```

Non-interactive smoke test:

```bash
claude-codex -p "Reply with exactly: hello"
```

## Why `CCB_LAUNCH_MODEL` exists

Claude Code performs client-side model validation before it even talks to the local bridge.

Because of that, some setups can only start reliably if `claude` is launched with a known alias such as `sonnet`, while the bridge itself still identifies the backend model publicly using the configured Codex/OpenAI model string.

This is not ideal, but it is the most robust workaround currently available without patching the Claude client itself.

If your Claude Code version accepts a direct public model string, set:

```bash
CCB_LAUNCH_MODEL=gpt-5.4
```

If it rejects that, use:

```bash
CCB_LAUNCH_MODEL=sonnet
```

## Native `claude` command

If you want `claude` itself to use the bridge-backed flow, install a small shim in a directory that appears before the real Claude binary in `PATH`:

```bash
claude-codex-install-shim --target ~/.local/bin/claude
```

The shim simply forwards to `claude-codex`, so you can type `claude` and get the bridge-backed setup by default.

## Dynamic model discovery

This project intentionally does not scrape undocumented Codex backend endpoints.

OpenAI documents a `GET /v1/models` API for API-key-based access, but that is not the same thing as a documented model entitlement listing for an OAuth-authenticated Codex CLI session. Sources:

- [OpenAI Models API reference](https://platform.openai.com/docs/api-reference/models/list)
- [OpenAI models catalog](https://developers.openai.com/api/docs/models)

Because of that, the safe public-repo approach here is explicit slot configuration instead of depending on private backend behavior.

## Development

Run the basic tests:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
