# Installing Prometheus Desktop on Windows

Prometheus Desktop 2.2.0 · Windows 10/11 64-bit · about 10 minutes.
(This is Prometheus, the solar orb. ATLAS Co-Pilot is a different app: see the repository's INSTALL.md.)

## 1. Get the installer
Download **Prometheus-Setup-2.2.0-x64-unsigned.exe** and **SHA256SUMS.txt** from the release page:
https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.2.0

Check the download (PowerShell, in the folder you downloaded to):
```
Get-FileHash .\Prometheus-Setup-2.2.0-x64-unsigned.exe -Algorithm SHA256
```
The result must match the value in `SHA256SUMS.txt` (also shown on the release page).

## 2. Install
Double-click the installer. It is **not code-signed**, so Windows SmartScreen says "Windows protected
your PC": choose **More info → Run anyway** only if the checksum matched.
* Installs for your user only (no administrator rights) into `%LOCALAPPDATA%\Programs\Prometheus`.
* Adds a Start-menu entry; a desktop shortcut is optional.
* Silent install: `Prometheus-Setup-2.2.0-x64-unsigned.exe /VERYSILENT /CURRENTUSER`.

## 3. First start
The birth of the sun plays once (click or press Esc to skip it), then a short welcome helps you connect a
model. Pick one:
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
Spoken replies (from 2.3.0): Settings → Voice → Spoken replies. Choose **On this computer** (press
*Set up local voice…*, pick a voice, about 27 MB engine + 65 MB per voice; speech is generated on your PC,
no internet needed afterwards, no reply text leaves it) or **Microsoft online voice** (the reply text is sent
to Microsoft; needs internet). Pick a voice and speed, press *Test voice*. If the chosen engine cannot speak,
replies stay as text: Prometheus never switches to the other engine by itself. In 2.2.0 and earlier, speech
always used Microsoft's online service.

Troubleshooting spoken replies: "not set up" → run *Set up local voice…*; "could not generate speech" →
*Repair or add voices…*; "could not be reached" (Microsoft) → check the internet or switch to the local voice;
"speaker could not be used" → check the Windows sound output device.
Voice input: open **Settings → Voice → Set up voice input**, pick a model (Base is recommended, 142 MB)
and press *Download and set up*. Prometheus downloads the whisper.cpp engine (4 MB, github.com) and the
model (huggingface.co), checks both against their published SHA-256, and from then on turns speech into
text on your PC. Talk then works in the Companion and in ORBIT, no restart needed. Remove the files from
the same dialog.

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
