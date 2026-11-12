# Cross-platform roadmap

Windows is first. The code is already split so the other platforms are adapter work plus validation.

| Item | Windows | macOS | Linux |
|---|---|---|---|
| App shell, pages, orb | built, CI-verified on a Windows VM | expected to work (PyQt6 + OpenGL 3.3 core): **not validated** | runs under Xvfb (screenshots); not tested on a desktop session |
| Data folder / workspace | adapter done | adapter done | adapter done |
| Credential store | Credential Manager (CI-verified via keyring on the runner) | Keychain via keyring: not validated | Secret Service via keyring: needs a running keyring daemon |
| Launch at login | HKCU Run key (code done; not exercised in CI) | LaunchAgent plist: not validated | XDG autostart: not validated |
| Tray + notifications | QSystemTrayIcon (not exercised in CI) | menu bar: not validated | depends on desktop (GNOME hides trays) |
| Packaging | PyInstaller + Inno Setup, CI | next: PyInstaller `.app` + `dmg`, needs signing + notarisation (Apple Developer ID) | next: AppImage or Flatpak |
| Global shortcut | not implemented | not implemented | not implemented |

## Order of work
1. Validate Windows on a physical PC (tray, notifications, sign-in start, DPI, a real GPU for the orb).
2. Code signing for Windows (certificate needed from the owner).
3. macOS: PyInstaller `.app`, check OpenGL 3.3 core context on Apple Silicon, Keychain, notarisation.
4. Linux: AppImage; test on GNOME (with AppIndicator) and KDE.
5. Global shortcut per platform (Windows `RegisterHotKey`, macOS Carbon/`NSEvent`, Linux portal).
