# Performance report

Measured in this environment: Linux container, 4 vCPU x86-64, **no GPU** (Mesa llvmpipe software
OpenGL under Xvfb), Python 3.13, PyQt6 6.12. Not measured on Windows hardware: CI runners report
only pass/fail timing.

## Start-up (self-test: core import, window, all 11 pages built and refreshed)
| Build | Run 1 | Run 2 | Run 3 | Peak RSS |
|---|---|---|---|---|
| From source (`python app/launcher.py`) | 3.10 s | 3.04 s | 2.94 s | ≈155 MB |
| Frozen (PyInstaller one-folder) | 3.56 s | 3.21 s | 3.13 s | ≈158 MB |

On the Windows CI VM the whole packaged self-test step (start, check, exit) took about 13 s
including PowerShell overhead; individual timings were not separated.

## Running (Xvfb, Companion page visible)
| State | CPU (one core) | Notes |
|---|---|---|
| Orb animating | ≈90 % | 626 frames in 10 s (≈63 fps), **software rendering**; a real GPU does this work instead: expect far lower CPU, unmeasured |
| Window minimised | 0.0 % | the orb timer stops when hidden or minimised |
| Reduced motion | 0.1 % | still orb, redrawn on state changes |
| RSS while running | ≈292 MB | includes software GL buffers |

## Size
| Artifact | Size |
|---|---|
| Linux one-folder build (local) | 318 MB (unstripped; includes Qt) |
| Windows installer / installed folder | see RELEASE_CHECKLIST (from the CI build report) |

## Notes and next steps
* Software GL is the worst case. On machines without a usable GPU, Settings → Reduce motion makes
  the orb still (0.1 % CPU).
* Possible later optimisation: lower the orb to 30 fps when the window is not focused.
* Whisper is not bundled (PyTorch would add more than 1 GB).
