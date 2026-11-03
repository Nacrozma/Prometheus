# Setup

## Prerequisites

| | Linux (tested: Ubuntu 24.04, x86_64) | macOS (not yet tested) | Windows (not yet tested) |
|---|---|---|---|
| Rust | 1.88+ (`rustup`) | same | same (MSVC toolchain) |
| Node.js | 22+ with pnpm 10 | same | same |
| System libraries | `libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev` | Xcode Command Line Tools | WebView2 (preinstalled on Windows 10/11), Visual Studio Build Tools |
| Credential store | A Secret Service provider (GNOME Keyring or KWallet) running in your session | Keychain (built in) | Credential Manager (built in) |

## Run in development

```bash
cd atlas
pnpm install
pnpm tauri dev
```

The first launch opens the setup wizard: your name and companion style, an explanation of where data lives,
connecting a model, choosing a workspace folder (optionally with a clearly labelled demo file), and a short
introduction to the Atlas Map.

## Configure your first provider

*Integrations → AI providers → Add provider* (or the wizard's "AI model" step):

* **Anthropic** — paste a key from console.anthropic.com. Suggested model: `claude-opus-5-5`.
* **OpenAI** — key from platform.openai.com; pick a model after testing the connection.
* **OpenAI-compatible** — e.g. OpenRouter (`https://openrouter.ai/api/v1`) or Groq; use that service's key.
* **Ollama** — install from ollama.com, `ollama pull qwen3` (or another model with tool support), keep
  the default endpoint `http://127.0.0.1:11434/v1`, no key.

"Save and test connection" lists the provider's models. A provider only shows **Connected** after that test
succeeds.

## Environment variables

Atlas does not read API keys from the environment. See `.env.example` for the development-only variables.

## Removing data

* Keys: Settings → Data → *Remove all keys* (or per provider: *Remove key*).
* Memories: Memory → *Delete all memories*.
* Everything: quit Atlas and delete the data folder shown in Settings → About; then remove the
  `atlas-copilot` entries from your OS credential store if any remain.
