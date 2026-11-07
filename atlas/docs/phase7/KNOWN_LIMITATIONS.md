# Known limitations (after Phase 7)

## Not verified (blocked in the test environment)

* **Live inference on every provider** (OpenAI, Anthropic, OpenRouter, Mistral, Cerebras, Ollama).
  * No keys were provided, and this environment's network blocks four of the provider hosts.
  * Only Anthropic's live rejection of a bad key was verified.
  * Run `cargo test -p atlas-core --test live_providers -- --ignored --nocapture` with your keys.
* **Real model inside Prometheus.**
  * The real Prometheus runtime was exercised end to end with a labelled scripted stand-in for its model.
  * The real tools, the dangerous-tool gate, the router and the adapter all ran for real.
  * A run with Prometheus's own model needs its key or a local Ollama.
* **The installed app's look on a Windows 10/11 desktop.**
  * Install, launch, data, upgrade and uninstall were verified on Windows Server 2025 (CI VM).
  * The desktop UI was verified by WebDriver e2e on Windows CI using the e2e build.
  * A person checking the release build's appearance on the target PC is still a manual step.

## Not implemented (and labelled so in the app)

* **Voice input:** push-to-talk transcription is not built; there is no microphone access.
* **Voice output:** only a "test system voice" button exists. Responses are not spoken; the
  `speak_responses` setting is stored but unused.
* **Desktop / OS notifications:** Atlas shows in-app notices only.
* **Remote sibling connectivity:** see REMOTE_CONNECTIVITY_PROPOSAL.md.
* **Shared Mission Workspace file transfer:**
  * Atlas shares text, which is objective, context and replies, and Prometheus receives it as
    `atlas_context.md` in its mission folder.
  * There is no file manifest, hash or patch transfer yet.
* **Atlas-side discipline recommendation:** the owner picks the Forge discipline. Auto routing uses it,
  but Atlas does not suggest one.
* **Mission plan and task allocation inside the ledger:**
  * Missions have an objective, mode, state, events and result.
  * There is no structured multi-task plan, dependency graph or per-task allocation yet.
* **Prometheus-side cancellation mid tool-call:** a delegated mission stops at the next step boundary
  (between model calls or between tool calls). A single long tool call is not interrupted.

## Behaviour to know about

* **Cost figures are estimates:** provider-reported tokens multiplied by the price schedule. Cache
  discounts, long-context surcharges and batch pricing are not modelled. Haiku 5.5 above 100K prompt
  tokens bills $0.50 / $2.50.
* **OpenAI seed prices:** gpt-5.4 and gpt-5.5 are unverified (not listed by OpenAI). gpt-5-nano and
  gpt-4.1 are deprecated. gpt-4.1-nano is shut down, and Atlas will not route to it.
* **With `--allow-dangerous`:** a delegated mission's `execute_shell` runs in Prometheus's folder, not the
  mission folder. The owner still confirms each command in Prometheus's terminal.
* **Installers are unsigned:** Windows SmartScreen shows "Windows protected your PC".
* **macOS:** builds and unit tests pass in CI, but the app has not been run interactively.
* **The avatar's star-birth intro** is a short scale-in, not Prometheus's full intro sequence.
