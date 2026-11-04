# ATLAS Co-Pilot on Windows

## Installing

1. Run **`ATLAS Co-Pilot_0.1.0_x64-setup.exe`**. It installs for the current user only (no administrator
   prompt) and adds Start-menu and desktop shortcuts. An `.msi` is also produced for managed installs.
2. **"Windows protected your PC"** (SmartScreen) appears because this build is not code-signed yet. Click
   **More info → Run anyway**. The warning disappears once the installer is signed (see below).
3. The installer includes Microsoft's WebView2 bootstrapper. Windows 10 (21H2+) and 11 already have WebView2;
   on older systems it is installed automatically (this needs an internet connection the first time).

Requirements: Windows 10 or 11, 64-bit.

## First launch

The setup wizard walks through your name and companion style, where data lives, connecting an AI model, and
choosing a workspace folder (the default is `Documents\Atlas Workspace`, which may sit inside OneDrive if
your Documents folder is synced).

## Where things are stored

| What | Where |
|---|---|
| Conversations, memories, projects, settings | `%APPDATA%\app.atlascopilot.desktop\atlas.db` |
| API keys | Windows Credential Manager → *Windows Credentials* → entries starting with `atlas-copilot` |
| Files Atlas creates | The workspace folder you chose |

## Uninstalling

*Settings → Apps → Installed apps → ATLAS Co-Pilot → Uninstall.* To also remove your data, first use
Settings → Data → *Remove all keys* inside Atlas (or delete the `atlas-copilot` entries in Credential Manager),
then delete `%APPDATA%\app.atlascopilot.desktop`.

## Code signing (removes the SmartScreen warning)

Options, cheapest first:

* **Azure Trusted Signing**: a Microsoft-managed signing service with a monthly subscription. Requires identity
  validation. It integrates with Tauri through a custom `bundle.windows.signCommand`.
* **OV code-signing certificate** from a certificate authority (stored on a hardware token or in a cloud HSM).
  SmartScreen reputation builds up over time.
* **EV certificate**: more expensive, with stronger initial reputation.

Once you have one, add its signing command or thumbprint to `src-tauri/tauri.conf.json` (`bundle.windows`) and store
secrets as GitHub Actions secrets. Never commit certificates or passwords.

## Known Windows specifics

* File names Atlas creates avoid Windows-reserved names (`CON`, `NUL`, `COM1`…), reserved characters and trailing
  dots or spaces.
* Keyboard shortcuts use **Ctrl** (Ctrl+K command palette, Ctrl+N new conversation, Ctrl+1…9 sections).
* The title bar follows Atlas's light or dark theme.
