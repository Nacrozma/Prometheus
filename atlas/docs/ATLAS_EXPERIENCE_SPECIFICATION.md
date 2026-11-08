# Experience specification

What the owner experiences, stage by stage. This page covers only what exists. Planned work is in
ATLAS_MASTER_ROADMAP.md.

## Identity (unchanged)

* Deep Orbit palette: deep navy, cyan and teal accents, and ice-blue highlights.
* The Atlas globe emblem, the Sora/Inter typography and the left rail.
* Prometheus keeps his gold solar avatar as a presence inside Atlas, never as its identity.

## First launch (Stage 1)

See ATLAS_FIRST_LAUNCH_EXPERIENCE.md.

## Personality (Stage 1)

**Where:** Settings → Companion, and step 2 of onboarding.

| Preset | Tone | Length | Initiative | Style line given to the model |
|---|---|---|---|---|
| Professional (default) | balanced | balanced | balanced | clear, courteous and businesslike |
| Friendly | warm | balanced | proactive | friendly and conversational; plain words over jargon |
| Analytical | precise | detailed | balanced | structured; states assumptions, weighs options, quantifies, keeps facts apart from inferences |
| Concise | precise | concise | reserved | minimal; answer first, no preamble |
| Detailed | balanced | detailed | proactive | thorough; reasoning, examples, edge cases |
| Creative | warm | balanced | proactive | imaginative; alternatives and fresh angles; speculation labelled |
| Custom | the owner's own choice | | | none |

**How the presets and axes interact:**
* Choosing a preset sets its tone, length and initiative.
* Changing any of those afterwards makes the personality Custom. The label never claims a preset the
  settings don't use.
* A profile from before presets loads as Professional if it matches the old defaults, otherwise as
  Custom. The owner's choices are kept.
* The rule lives in the core (`CompanionSettings::apply_personality`). The UI only shows it.

**Custom instructions:**
* Up to 2000 characters, refused if they look like a key or password.
* Only Atlas's own model receives them, placed below the honesty, untrusted-content and permission
  rules and marked as unable to change them.
* They are never part of a mission or anything sent to Prometheus. This is tested against the real
  adapter.

**Personality never overrides** accuracy, privacy or safety. Those rules come first in the system
prompt and are enforced by the core, not by the model.

## Conversation (Stage 1)

* **Regenerate:**
  * Replaces the last reply with a new one, from the reply's actions or with Ctrl/⌘+Shift+Enter.
  * The question is kept, not duplicated.
  * The old reply is removed and not sent to the model.
* **Try again:** after a request that failed with no reply, it answers the same message again.
* **Safety rule:**
  * A reply that used tools is never regenerated, because answering again could repeat an action.
    For those, "Ask again" asks the question anew below and keeps the record.
  * The core enforces this and refuses with a clear message.
* **Copy conversation:** conversation menu → Copy conversation. Copies Markdown with "You" and
  "Atlas" headings; tool use is summarised, not dumped.
* **Stop:** Esc stops a running reply, as does the Stop button.
* Shortcuts are listed in Settings → Shortcuts.
