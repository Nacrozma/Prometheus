# How to install ATLAS Co-Pilot (Windows)

ATLAS Co-Pilot is a desktop AI companion. This page gets it running on a Windows PC in about 10 minutes.

**You need:** Windows 10 or 11 (64-bit), an internet connection, and one AI service: either an API key from
Anthropic or OpenAI, or the free Ollama app if you'd rather run AI on your own PC (see step 4).

---

## 1. Download

**[⬇ Download ATLAS-Co-Pilot-Setup-x64.exe](https://github.com/Nacrozma/Prometheus/releases/download/atlas-v0.1.0/ATLAS-Co-Pilot-Setup-x64.exe)** (8.5 MB)

All files for this version are on the [release page](https://github.com/Nacrozma/Prometheus/releases/tag/atlas-v0.1.0):

| File | What it is |
|---|---|
| `ATLAS-Co-Pilot-Setup-x64.exe` | **The installer. Use this one.** |
| `ATLAS-Co-Pilot-x64.msi` | The same app as an MSI package, for IT-managed PCs. Most people don't need it. |
| `SHA256SUMS.txt` | Checksums, to confirm the download isn't damaged (optional, see the end of this page). |

## 2. Install

1. Open your **Downloads** folder and double-click **`ATLAS-Co-Pilot-Setup-x64.exe`**.
2. Windows will probably show a blue box saying **"Windows protected your PC"**. The app isn't code-signed
   yet, which costs money, so Windows doesn't recognise the publisher. Click **More info**, then **Run anyway**.
3. Follow the installer (Next → Install → Finish). It installs only for your Windows account, so it won't ask for
   an administrator password.
4. If your PC is missing Microsoft's WebView2 component (rare on Windows 10/11), the installer downloads it
   automatically.

ATLAS Co-Pilot is now in the **Start menu**, with a shortcut on the desktop.

## 3. First launch

Open **ATLAS Co-Pilot**. A short setup walks you through:

1. **Welcome:** click *Get started*.
2. **About you:** what Atlas should call you and how it should talk (all optional).
3. **Your data:** where things are stored. Just read and continue.
4. **AI model:** connect the AI service (step 4 below).
5. **Workspace:** click **Use Documents/Atlas Workspace**. This is the only folder Atlas may create files in.
   You can add a small sample file to try things with.
6. **The Atlas:** a quick look at the map of what Atlas can do.
7. **Ready:** click **Start your first conversation**.

## 4. Connect an AI service (pick one)

Atlas needs an AI model to think with. Pick **one** of these:

### Option A: Anthropic (Claude). Recommended.
1. Go to **[console.anthropic.com](https://console.anthropic.com)** and create an account.
2. Open **Billing** and add a small amount of credit (for example $5). Usage is pay-as-you-go.
3. Open **API Keys**, click **Create Key**, and copy it (it starts with `sk-ant-`).
4. In Atlas, at the **AI model** step (or later under **Integrations → Add provider**), choose
   **Anthropic (Claude)**, paste the key, and click **Save and test connection**.
5. You should see **Connected**. The default model is `claude-opus-5-5`; you can switch to a cheaper model
   in the provider card's **Default model** menu.

### Option B: OpenAI
1. Go to **[platform.openai.com](https://platform.openai.com)**, add billing credit, then open **API keys** and
   create a key.
2. In Atlas choose **OpenAI**, paste the key, click **Save and test connection**, then pick a model from the list.

### Option C: Ollama. Free, and runs entirely on your PC.
1. Download and install Ollama from **[ollama.com](https://ollama.com)**.
2. Open **Command Prompt** and run: `ollama pull qwen3`. This downloads a model, several GB.
3. In Atlas choose **Ollama (on this computer)**, type `qwen3` as the model, and click **Save and test connection**.

   Local models need a reasonably powerful PC (16 GB of RAM or more recommended) and are slower than cloud models.

**About your key:** Atlas stores it in Windows Credential Manager, never in plain text, and never shows it again.
Only the AI service you chose receives your messages.

## 5. Try it

- Ask anything, e.g. *"Help me plan a relaxing weekend."*
- Ask it to *"draft a short note thanking a friend and save it."* Atlas will ask your **approval** before it
  creates the file. Click **Approve** and the file appears in `Documents\Atlas Workspace\Drafts`.
- Open **Atlas Map** (the orbit icon on the left) to see everything Atlas can use.
- Press **Ctrl + K** at any time to search for any command.

---

## Uninstalling

1. *(Optional, to remove your saved key)* In Atlas: **Settings → Data & privacy → Remove all keys**.
2. Windows **Settings → Apps → Installed apps → ATLAS Co-Pilot → Uninstall**.
3. *(Optional, to delete your conversations and memories)* Press **Win + R**, type
   `%APPDATA%\app.atlascopilot.desktop`, press Enter, and delete that folder.

Files Atlas created in `Documents\Atlas Workspace` are yours and are left in place.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Windows protected your PC" | Click **More info → Run anyway** (see step 2). |
| The provider says **Authentication failed** | The key was mistyped or revoked. Go to **Integrations**, click **Replace key**, paste a fresh key, then **Test connection**. |
| **Rate limited** or **No credit** errors | Add credit / wait a minute on the provider's website. |
| Ollama: "couldn't reach the provider" | Make sure Ollama is running (its icon is in the system tray) and that you pulled a model. |
| Something looks wrong | **Settings → Diagnostics → Copy** gives a report with no messages or keys in it. Send it to whoever set this up for you. |

## Checking the download (optional)

In PowerShell, in your Downloads folder:

```powershell
Get-FileHash .\ATLAS-Co-Pilot-Setup-x64.exe -Algorithm SHA256
```

For version 0.1.0 it must be:

```
D136137A54F05D81E8E3B36B1D59427B55CA39BC002737AC7F47D1E4F6C70913
```

(The same values are in `SHA256SUMS.txt` on the release page.)

---

*Other systems:* Windows is the supported platform for this release. To build ATLAS Co-Pilot on macOS or Linux,
see [atlas/docs/SETUP.md](atlas/docs/SETUP.md). More detail on Windows (data locations, code signing) is in
[atlas/docs/WINDOWS.md](atlas/docs/WINDOWS.md).
