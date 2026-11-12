# Installing Prometheus Desktop on Windows

Prometheus Desktop 0.1.0 · Windows 10/11 64-bit · about 10 minutes.
(This is Prometheus, the solar orb. ATLAS Co-Pilot is a different app: see the repository's INSTALL.md.)

## 1. Get the installer
The installer is built by the `prometheus-desktop` workflow on GitHub Actions and attached to the run
as the artifact **prometheus-desktop-windows-x64-unsigned** (kept 14 days). It contains:
`Prometheus-Setup-0.1.0-x64-unsigned.exe`, `SHA256SUMS.txt`, `build-report.txt` and the self-test
reports. It has **not** been published as a release.

Check the download (PowerShell):
```
Get-FileHash .\Prometheus-Setup-0.1.0-x64-unsigned.exe -Algorithm SHA256
```
The result must match `SHA256SUMS.txt`.

## 2. Install
Double-click the installer. It is **not code-signed**, so Windows SmartScreen says "Windows protected
your PC": choose **More info → Run anyway** only if the checksum matched.
* Installs for your user only (no administrator rights) into `%LOCALAPPDATA%\Programs\Prometheus`.
* Adds a Start-menu entry; a desktop shortcut is optional.
* Silent install: `Prometheus-Setup-0.1.0-x64-unsigned.exe /VERYSILENT /CURRENTUSER`.

## 3. First start
Prometheus opens on **Settings** the first time. Pick one:
* **A cloud provider**: paste an OpenRouter, Groq or Cerebras key and press *Save*. It is stored in
  Windows Credential Manager (entry "Prometheus Desktop"), not in a file.
* **Ollama (free, local)**: install Ollama, run `ollama pull llama3.2` and `ollama serve`, then press
  *Reconnect providers*.
* Already have a `.env` with keys? Put it in `%APPDATA%\Prometheus\.env`; it is read at start and wins.

Optional: Settings → Workspace to choose the folder the file and shell tools may use (default
`Documents\Prometheus Workspace`); Settings → Desktop for tray, notifications, start at sign-in and
reduced motion.

## 4. Bring your existing data (optional)
If you used Prometheus from a source folder: Settings → Data → *Import data from another Prometheus
folder…*, choose that folder, confirm, then quit and reopen Prometheus. Your old folder is only read;
anything replaced is backed up under `%APPDATA%\Prometheus\backups\`. See DATA_MIGRATION.md.

## 5. Use it
Companion: type and press Enter. When Prometheus wants to write a file, run a command, run code or
export to Obsidian, an approval card shows the exact action: **Deny** is the default. Esc stops.
Ctrl+K jumps anywhere.

## Voice
Speech output works if your PC has internet (Microsoft edge-tts; the spoken text is sent to it).
Voice input (Whisper) is not included in the installer because it needs PyTorch (>1 GB); it works
when running from source with `pip install openai-whisper`.

## Upgrading
Run a newer installer: it replaces the program in place and keeps your data and keys.

## Uninstalling
Settings → Apps → Prometheus → Uninstall. Your data (`%APPDATA%\Prometheus`) and stored keys stay.
To remove them too: delete that folder and the "Prometheus Desktop" entries in Credential Manager
(Control Panel → Credential Manager → Windows Credentials).

## Troubleshooting
* **Nothing happens when I start it again**: Prometheus is already running (maybe in the tray); the
  existing window is brought forward.
* **"The orb needs OpenGL 3.3"**: update the graphics driver; everything else still works.
* **High CPU on a PC without a graphics card**: Settings → Reduce motion.
* **It will not start**: see `%APPDATA%\Prometheus\desktop_crash.log`.
* **Check an install without opening the window**: `Prometheus.exe --self-test=%TEMP%\pt.json`.
