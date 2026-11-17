# Motion system

| Motion | Duration · easing | Meaning | Reduce motion |
|---|---|---|---|
| Launch sequence | 7.5 s timeline + 0.9 s hold + 0.65 s fade (InOutCubic) | Prometheus is born / ready | skipped |
| Avatar state change | tint/dim/energy eased per frame (k = 0.08 at 60 fps ≈ 0.4 s) | what Prometheus is doing | still sun, still sign |
| State signs | orbit 1.1–1.5 rad/s; sweep 90°/s; dashed ring 40°/s; blocks 55°/s; arcs 80°/s; ripples 0.7 Hz | the kind of work | drawn still |
| Audio signs | follow the real level each frame; the level decays ×0.85/frame when audio stops | listening / speaking | drawn still at the current level |
| Toast | appears at once; fades out 220 ms (OutCubic) after 4.2 s (ok/info) or 7 s (attention/problem) | result of an action | no fade |
| Streaming text | re-rendered at most every 50 ms | a reply arriving | unchanged (it is content) |
| Painted sun | 30 fps while visible | life on Home | still |

Rules: motion only communicates state; nothing waits for an animation before it can be used; nothing
animates on hover except colour and border changes; there are no page transitions that delay navigation.
