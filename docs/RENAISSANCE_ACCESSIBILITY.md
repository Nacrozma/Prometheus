# Accessibility

| Area | What is in place | How it was checked |
|---|---|---|
| Keyboard | Every section by Ctrl+1–9 and Tab; palette ↑↓ skipping group headers, Enter, Esc; composer Enter / Shift+Enter; Esc stops; memory map ← → and Enter; arm sliders arrows and Page Up/Down; launch skips with Esc/Enter/Space | Interaction guide; window smoke test drives navigation |
| Focus | Champagne focus outline on buttons, inputs, nav items, decision buttons | Screenshots |
| Names | Accessible names on new controls (composer, approval decisions name the action, map, charts, timelines, lists); charts carry text descriptions of their numbers | Code review |
| Status not by colour alone | Toasts have an icon and a word (Done, Working, Attention, Problem); avatar states have a shape and words; outcomes in Trust have icon + word; reliability bars mark "few" samples in text | Screenshots |
| Announcements | Toast text is set as the window's accessible description | Code |
| Motion | Reduce motion stills the suns and signs, removes toast fades and skips the launch | Settings test in smoke run; code |
| Contrast | Primary text ≈ 18:1, secondary ≈ 6.8:1 on the background; gold ≈ 10:1 | Token values |
| Text size | Base 10 pt, nothing smaller than 8 pt (captions) | Design tokens |

Not verified: a real screen reader (NVDA/Narrator) on Windows; Windows text scaling above 150 %.
