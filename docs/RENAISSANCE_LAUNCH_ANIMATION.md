# The birth of the sun (launch sequence)

Code: `app/ui/launch.py` (overlay, wordmark, painted fallback), timeline and shader `gui_birth.py`
(shared with the HUD, unit-tested in `tests/test_gui_modules.py`). Screenshots `00a`–`00e`.

| Phase (timeline t) | Seconds | What is drawn | Directive phase |
|---|---|---|---|
| 0.00–0.24 | 0.0–1.8 | Dark nebula and faint stars; the cloud begins to collapse | The void |
| 0.24–0.56 | 1.8–4.2 | A protostar with an accretion disk and faint bipolar jets: the first light | The first light |
| 0.54–0.70 | 4.0–5.3 | Fusion ignition: the core surges | Ignition |
| 0.70 | 5.3 | Flash and shockwave | Ignition |
| 0.70–1.00 | 5.3–7.5 | The star grows to full size; the nebula disperses; the corona settles | Solar formation |
| 0.80–1.00 | 6.0–7.5 | PROMETHEUS fades in below the sun, letter spacing tightening | Identity reveal |
| after 1.00 | +0.9 s, then 0.65 s fade | The overlay fades and Home is underneath | Transition |

* **Never blocks start-up:** the window is fully built first; the overlay sits on top. A safety timer
  reveals the app after 11.5 s whatever happens; an exception skips the sequence.
* **Skip:** click, Esc, Enter or Space (fast-forwards the timeline, then fades).
* **Policy:** once per application start; not when restoring from the tray; not on navigation.
  Settings → Appearance turns it off; Reduce motion skips it.
* **Fallback:** without OpenGL 3.3 a painted version (dust collapsing, a growing core, the shockwave, the
  wordmark) runs on the same timeline.
* **First run:** onboarding opens after the sequence.
* **Performance:** the shader runs at 60 fps only while the overlay is visible; it is deleted afterwards.
