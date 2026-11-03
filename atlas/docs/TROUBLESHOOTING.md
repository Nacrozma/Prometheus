# Troubleshooting

**"No system credential store is available" (Linux).** Atlas stores keys only in the Secret Service. Install and
run GNOME Keyring (`gnome-keyring`) or KWallet, and make sure your session has a D-Bus session bus. Settings →
Diagnostics shows the credential-store status.

**A provider shows "Authentication failed".** Replace the key in Integrations and press *Test connection*.

**"Rate limited" / "Temporarily degraded".** Atlas retries twice with back-off, then stops. Wait and try again.

**"Atlas will not switch to another provider automatically".** Your default provider is unusable. Fix it, choose
another model for this conversation, or enable cross-provider fallback in Settings → Models.

**Ollama: "couldn't reach the provider".** Start Ollama (`ollama serve`) and pull a model. If the model doesn't
support tools, Atlas continues without them and tells you.

**File tools say "choose a workspace folder".** Settings → File workspace, or Files → Choose folder.

**"Reading .pdf files is not supported yet".** Only UTF-8 text formats can be read in this version.

**A task shows "Interrupted".** Atlas was closed while it ran. Nothing resumes automatically; review its steps in
Mission Control and dismiss it.

**Blank map or page.** Each page has its own error boundary; use *Try again*, then check Settings → Diagnostics.

**Linux under a VM/remote desktop: blank window.** Try `WEBKIT_DISABLE_COMPOSITING_MODE=1`.
