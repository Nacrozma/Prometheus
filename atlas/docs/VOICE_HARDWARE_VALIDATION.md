# Voice: validation on real hardware

**Status: PARTLY DONE.** On 2026-11-12 the owner reported, on their own PC with 0.4.2: voice "running
perfectly", "so smooth", with "a slight delay in the answer". That is a real-hardware pass for basic use.
It came without measurements, so the delay is not quantified and nothing has been tuned.

Before that report, no microphone or speaker had been tested on any machine. Everything proven so
far ran on cloud machines without audio devices (real engines, but the "speech" was synthetic).

This page is the checklist for the owner's PC. Atlas measures what it can; the rest is your judgement.
Paste each report under "Results" (or send it back) and the numbers become the record.

## How to run it

1. Install Atlas 0.4.1 or later and set up voice (INSTALL.md, step 6).
2. Open **Settings → Voice → Voice check**.
3. **Speakers:** click **Play test sentence**, then answer what you heard.
4. **Microphone:** choose the conditions, click **Start**, read the sentence shown, click **Stop**.
5. Repeat for each row below, then click **Copy report**.

The report holds timings, device names and the recognised text. It contains no audio and is not sent
anywhere.

## Checklist

| # | Test | How | Pass when |
|---|---|---|---|
| 1 | Speakers | Voice check → Play test sentence | Heard clearly; first sound within about 3 s |
| 2 | Headphones | Choose them under **Play through** (or as the Windows default), repeat 1 | Heard clearly in the headphones only |
| 3 | Microphone, quiet room | Voice check, "Quiet room", 3 attempts | 93% of words or better |
| 4 | Background noise | Music or a fan on, "Background noise", 3 attempts | 80% or better; note what was misheard |
| 5 | Fast and slow speech | "Speaking fast", "Speaking slowly" | 80% or better |
| 6 | Second microphone | Choose another under **Microphone**, repeat 3 | Works; the report names the device |
| 7 | Another speaker or accent | Someone else reads the sentence | Note the score |
| 8 | Short request | Companion: mic, say "What time is it?" | Text appears in the box, correct |
| 9 | Long request | Speak for 20–30 s | Text complete; no cut-off |
| 10 | Spoken reply | Turn on **Read replies aloud**, ask a question | Sentences flow without long gaps |
| 11 | Interrupt | Press **Esc** mid-reply | Silence at once; the reply text stays; nothing is re-sent |
| 12 | Repeated use | Ten push-to-talk requests in a row | All work; no slowdown |
| 13 | Unplug the microphone while listening | | A clear message; typing still works |
| 14 | Plug it back in | | Listening works again without a restart |
| 15 | Offline | Turn off Wi-Fi after setup | Voice still works both ways |
| 16 | Remove and reinstall a model | Settings → Voice → Remove, then download | Works again |
| 17 | Reduced motion | Settings → Appearance → Reduced | The ring is still; voice works |
| 18 | Each model you have | Select tiny, base, small in turn; repeat 3 | Compare accuracy and speed |

## Choosing the default model

The default stays **base** until real results say otherwise. Rule:
* If base scores under 90% in a quiet room on the owner's microphone and small scores clearly better
  while answering within about twice the speech length, recommend small on PCs with 8+ cores.
* If base takes longer than the speech itself, recommend tiny on that class of PC.

## Results

*None yet.*

| Date | PC | Microphone | Output | Model | Quiet-room accuracy | Recognition time | First sound | Notes |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
