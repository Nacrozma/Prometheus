# Privacy

**Stored on this computer** (in the app data folder shown in Settings → About):
conversations, memories, projects, settings, task history, tool step inputs/outputs (secrets redacted),
usage counts, and a content-free activity log. Delete them from within the app, or remove the folder.

**Stored in your OS credential store:** API keys (Keychain, Windows Credential Manager, or Secret Service).

**Sent to an AI provider when you send a message:** your message, the conversation history that fits the
model's context, Atlas's system prompt (identity, your companion preferences, the active project's
instructions), the local time, relevant memories (only those that match, plus ones you pinned), and the
descriptions of the tools that are enabled. Tool results produced during the turn are sent back to the same
provider. Nothing is sent to any other party.

**Local processing:** with Ollama, messages stay on this machine (unless your Ollama is configured to use a
remote server).

**Never sent anywhere:** API keys, memories that are not relevant, files you have not asked Atlas to read,
telemetry. Atlas has no analytics.

**Web search:** only the search query is sent to Tavily, after your approval (by default).

**Exports and backups** exclude keys. Diagnostics reports contain no message content and are saved only when
you choose to.

**Retention:** optional automatic deletion of old conversations and activity-log entries (Settings → Data).
