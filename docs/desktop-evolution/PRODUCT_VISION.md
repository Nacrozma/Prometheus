# Prometheus Desktop: product vision

Prometheus is a personal engineering companion: a solar orb you talk to, that remembers what matters,
calculates, plans, builds small tools for itself, and never acts on the world without asking.
Until now it lived in a terminal and a single HUD window started from a source checkout. The desktop
application makes it something you **install, open from the Start menu and keep running**, without
losing what made it Prometheus.

## Who it is for
One owner, on their own Windows PC (macOS and Linux later), who wants an assistant that:
* talks naturally and shows its state through the orb (idle, thinking, speaking, waiting for you);
* remembers facts with their source and trust level, and lets them correct it;
* does real engineering arithmetic (structures, aerodynamics, orbital mechanics) with stated limits;
* plans and simulates a 4-joint robot arm, never claiming hardware it has not touched;
* reminds them of things, even across restarts;
* keeps an auditable record of everything it did.

## Principles
1. **One brain.** The desktop app is a shell around the existing core. Same tools, same memory, same
   safety policy as the terminal. Nothing is re-implemented.
2. **Ask before acting.** Tools with real-world effects show an approval card. Auto-approve exists,
   is off by default, warns before it is turned on and is shown in the status bar while on.
3. **Honest about limits.** Simulation is labelled simulation; synthetic evaluations are labelled
   synthetic; unavailable voice says why; an unsigned installer says it is unsigned.
4. **Your data stays yours.** Data lives in a per-user folder; keys in the OS credential store; the
   installer contains neither, and uninstalling keeps both.
5. **Calm by default.** Dark charcoal and warm gold; reduced-motion option; the orb stops drawing
   when nobody can see it.

## Out of scope for 0.1
Real robot-arm control from the desktop app, cloud sync, multiple users, a plugin marketplace,
mobile companions.
