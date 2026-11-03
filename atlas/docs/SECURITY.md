# Security

## Threat model (summary)

| Threat | Control |
|---|---|
| Model (or injected text) tries to perform an unapproved action | Policy + approvals enforced in `atlas-core`; approvals bound to tool + argument hash, single-use; destructive class always denied |
| Prompt injection via files, web pages, tool output | Delivered only as tool results / `<atlas_context>` data; system prompt marks them untrusted; they cannot create or decide approvals (approvals are decided only through the `approval_decide` IPC command from a user click) |
| Arguments changed between approval and execution | Hash re-computed in `execute_authorized`; mismatch → denied (tested) |
| Replay / duplicate execution | Approval status `approved → consumed` in one transaction (tested) |
| Credential leakage | Keys only in OS credential store; never returned over IPC; masked hint only; redaction on errors, audit, step records, diagnostics, saved text; no key in prompts (tested) |
| Path traversal / symlink escape | Relative paths only, `..`/absolute rejected, canonicalised containment checks per directory component, `O_NOFOLLOW` + `create_new` (never overwrite) (tested) |
| Webview compromise / XSS from model output | Markdown rendered without raw HTML; `javascript:` and non-http(s) URLs dropped; remote images never fetched; strict CSP (`script-src 'self'`, no remote connect); navigation guard blocks leaving the app; IPC limited to the explicit command list |
| Cleartext key transport | Provider base URLs must be `https://` (plain `http://` allowed only for localhost) |
| Silent data egress | No telemetry. Network tools ask first by default; offline mode blocks cloud providers and network tools; cross-provider fallback off by default and announced |
| Crash mid-task | Restart marks active tasks `interrupted`, expires pending approvals, never resumes |
| Malicious backup file | Opened read-only, `integrity_check`, schema version and marker table verified, user confirms with typed phrase |

## Permission classes

| Class | Default | Configurable |
|---|---|---|
| Read-only (local) | Allowed | No |
| Read-only (sends data off-device, e.g. web search) | Ask | Ask / Allow |
| Local write (create files, save memory) | Ask | Ask / Allow |
| Consequential (send, publish, purchase) | Ask | **No** |
| Destructive / privileged | Deny | **No** |

No built-in tool is consequential or destructive in this version; the classes are enforced and tested with
test-only tools (`test.send_message`, `test.destroy`).

## Desktop hardening

* **Capabilities:** the main window may only listen to events (`core:event:allow-listen/unlisten`). No fs,
  shell, http, or dialog plugin API is exposed to JavaScript; dialogs open from Rust.
* **CSP:** `default-src 'self'; script-src 'self'; connect-src ipc: http://ipc.localhost; img-src 'self' data:;
  object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'`. `style-src` allows
  `'unsafe-inline'` (and Tauri's nonce injection for styles is disabled) because the graph and toast
  libraries set inline styles; scripts remain locked down.
* **`freezePrototype` is off.** Freezing `Object.prototype` broke the graph library (d3 assigns `constructor`
  on its own objects — the "override mistake"), crashing the Atlas Map. With script sources restricted to the
  bundled app, the prototype-pollution vector this guards against requires code execution we already block.
* **Navigation guard:** the window can only load the bundled app; links open in the system browser on click,
  via a command that accepts only `http(s)` URLs.
* **No local server** is started; there is no network-exposed backend.

## Known limitations

* The OS credential store protects keys at rest from other users; it does not protect against malware
  running as you.
* Data sent to a cloud provider is processed under that provider's terms.
* The e2e build (`--features e2e`) uses in-memory keys and a scripted provider; it is for automated tests only
  and labels itself in Settings → About.

## Reporting

Security issues: open a private report with the maintainer. Never include API keys in issues or logs.
