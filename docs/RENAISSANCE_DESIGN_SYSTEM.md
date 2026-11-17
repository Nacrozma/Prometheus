# Prometheus 2.0: design system (Solar × Cosmic)

Source of truth: `app/ui/theme.py` (tokens and stylesheet), `app/ui/icons.py` (line icons),
`app/ui/widgets.py` (shared components), `app/ui/sun.py` and `app/ui/solar.py` (the solar presence).
Pages use semantic tokens, never raw colours.

## Palette and semantic tokens

| Token | Value | Use |
|---|---|---|
| `BG` | `#08090E` deep space | window background |
| `SURFACE` | `#10131B` cosmic graphite | sidebar, cards |
| `SURFACE_ELEVATED` | `#171A23` | inputs, user messages, hover |
| `SURFACE_RAISED` | `#1E2230` | pressed, tooltips |
| `TEXT` / `TEXT_SECONDARY` / `TEXT_FAINT` | `#F4F3EF` / `#9297A6` / `#6B7080` | text levels |
| `ACCENT` | `#F4B52C` solar gold | primary actions, active navigation, links |
| `SECONDARY_ACCENT` | `#FF8A24` amber | tool activity, approval cards |
| `BRONZE` | `#A86B2D` | selection, disabled primary, scrollbar hover |
| `HIGHLIGHT` / `FOCUS` | `#F7D98B` champagne | focus rings, formulas, listening |
| `BORDER` / `BORDER_STRONG` / `BORDER_WARM` | `#242733` / `#343847` / `#4A3A1E` | outlines |
| `OK` / `WARN` / `ERR` / `INFO` | `#5FD39A` / `#F6B44B` / `#FF6B5E` / `#7DB8FF` | status |
| `SOLAR_GLOW` | amber at 18 % | hero gradient |

Contrast on `BG`: primary text ≈ 18:1, secondary ≈ 6.8:1, faint ≈ 3.9:1 (used only for captions at
large-enough sizes or with redundant meaning), gold ≈ 10:1. Status pills use `rgba()` backgrounds
(Qt reads `#RRGGBBAA` as `#AARRGGBB`, a bug found in visual QA and fixed).

## Typography
Segoe UI Variable (Windows), falling back to Inter and Noto Sans; display face for titles and numbers;
Cascadia Code / JetBrains Mono / Consolas for code. Sizes: base 10 pt, small 9, caption 8, H2 12, H1 18,
statistics 20. Eyebrows (navigation group above each page title) in gold caps with letter spacing.

## Spacing, radii
4 / 8 / 12 / 16 / 24 / 32 px; radii 6 (controls), 8 (lists), 12 (cards, composer, approval).

## Components
`Page` (eyebrow, title, subtitle, actions, optional scroll) · `Card` (title with icon; interactive variant)
· `pill(text, tone)` · `stat_tile` · `EmptyState` · `icon_button` · `divider` · buttons `primary`, `ghost`,
`danger`, `link`, checked state · `NavBar` (grouped, collapsible, tooltips) · `CommandPalette` ·
notification bell · `ApprovalCard` · `Composer` (multiline) · `MemoryDialog` · `Onboarding`.

## Experience components (experience-first pass)
Rail (`QFrame#rail`, `QListWidget#rail`) for section-local navigation · inspector (`QFrame#inspector`) for
the selected item · readable rows (`QListWidget#rows`) instead of tables · `homeRow` items with an icon,
two lines and one action · chips (`QPushButton#chip`) for segmented choices · `viewport` for the arm ·
toasts and the activity drawer (`app/ui/feedback.py`) · page header variants (`full`, `compact`, `none`) so
screens compose their own top area. Reusable pieces stay generic; screens decide their composition.

## Icons
33 original line icons (24 × 24, 1.75 stroke, round caps) rendered from SVG at any size and tinted per
state. No icon font or third-party icon set is bundled.

## Motion
Only meaningful motion: the sun (state and real audio level), the activity arc while working, streaming
text. Reduce motion (Settings) stills both suns; the shader sun stops when the window is hidden or
minimised and drops to 30 fps when the window is not active; the painted sun runs at 30 fps only while
visible.
