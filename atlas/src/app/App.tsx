import * as RadixTooltip from "@radix-ui/react-tooltip";
import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Toaster } from "sonner";
import { Emblem } from "@/components/Emblem";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Button } from "@/components/ui/primitives";
import { FirstLaunch } from "@/features/first-launch/FirstLaunch";
import { shouldPlayAtStartup } from "@/features/first-launch/sequence";
import { Onboarding } from "@/features/onboarding/Onboarding";
import { api, isTauri } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { Settings } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { Shell } from "./Shell";

/** Apply appearance settings to the document root (theme, motion, font scale). */
export function applyAppearance(s: Settings | undefined) {
  const root = document.documentElement;
  const theme = s?.appearance.theme ?? "dark";
  const resolved = theme === "system" ? (window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark") : theme;
  root.dataset.theme = resolved;
  // Match the native title bar (Windows 10/11, macOS). Cosmetic: ignore failures.
  if (isTauri()) void getCurrentWindow().setTheme(resolved).catch(() => {});
  root.dataset.motion = s?.appearance.motion ?? "system";
  root.style.setProperty("--font-scale", String((s?.appearance.font_scale ?? 100) / 100));
}

function Splash({ leaving }: { leaving: boolean }) {
  return (
    <div
      data-splash
      className="atmosphere fixed inset-0 z-50 grid place-items-center bg-bg-0 transition-opacity duration-[var(--dur-slow)]"
      style={{ opacity: leaving ? 0 : 1, pointerEvents: leaving ? "none" : "auto" }}
      aria-hidden={leaving}
    >
      <div className="flex flex-col items-center gap-5 anim-fade">
        <Emblem size={96} animated glow />
        <div className="text-center">
          <p className="font-display text-lg font-semibold tracking-[0.32em] text-text-1">ATLAS</p>
          <p className="mt-1 text-xs uppercase tracking-[0.3em] text-text-3">Co-Pilot</p>
        </div>
      </div>
    </div>
  );
}

function NotInDesktop() {
  return (
    <div className="atmosphere grid h-full place-items-center bg-bg-1 p-8">
      <div className="max-w-md text-center">
        <Emblem size={72} className="mx-auto" glow />
        <h1 className="mt-6 font-display text-xl font-semibold">ATLAS Co-Pilot runs as a desktop app</h1>
        <p className="mt-2 text-sm text-text-2">
          This interface talks to Atlas's trusted core, which only exists inside the desktop application. Start it with{" "}
          <code className="rounded-xs bg-bg-3 px-1 font-mono">pnpm tauri dev</code>.
        </p>
      </div>
    </div>
  );
}

export function App() {
  const settings = useAtlasQuery("settings", () => (isTauri() ? api.settings() : Promise.reject(new Error("no core"))), ["settings"]);
  const [minDelayDone, setMinDelayDone] = useState(false);
  const [onboardingDone, setOnboardingDone] = useState<boolean | null>(null);
  const [splashGone, setSplashGone] = useState(false);
  // The introduction: decided once from the stored state, so finishing it doesn't re-trigger it.
  const [introAtStartup, setIntroAtStartup] = useState<boolean | null>(null);
  const introReplay = useUi((s) => s.introReplay);
  const setIntroReplay = useUi((s) => s.setIntroReplay);

  useEffect(() => {
    const motionReduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const t = setTimeout(() => setMinDelayDone(true), motionReduced ? 0 : 900);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    applyAppearance(settings.data);
    if (settings.data && onboardingDone === null) setOnboardingDone(settings.data.onboarding_completed);
    if (settings.data && introAtStartup === null) setIntroAtStartup(shouldPlayAtStartup(settings.data.first_launch.completed_at));
  }, [settings.data, onboardingDone, introAtStartup]);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: light)");
    const h = () => applyAppearance(settings.data);
    mq?.addEventListener("change", h);
    return () => mq?.removeEventListener("change", h);
  }, [settings.data]);

  const ready = Boolean(minDelayDone && (settings.data || settings.error));
  // Remove the splash from the page once its fade-out has finished.
  useEffect(() => {
    if (!ready) return;
    const t = setTimeout(() => setSplashGone(true), 600);
    return () => clearTimeout(t);
  }, [ready]);

  if (!isTauri()) return <NotInDesktop />;

  const intro = settings.data ? (introAtStartup ? "first" : introReplay ? "replay" : null) : null;

  return (
    <RadixTooltip.Provider>
      <div className="h-full" inert={intro !== null}>
      {settings.error && !settings.data ? (
        <div className="grid h-full place-items-center p-8">
          <div className="max-w-md text-center">
            <h1 className="font-display text-lg font-semibold">Atlas couldn't start</h1>
            <p className="mt-2 text-sm text-text-2">{settings.error.message}</p>
            <Button className="mt-4" onClick={settings.reload}>
              Try again
            </Button>
          </div>
        </div>
      ) : settings.data && onboardingDone === false ? (
        <Onboarding settings={settings.data} onDone={() => setOnboardingDone(true)} />
      ) : settings.data ? (
        <ErrorBoundary label="Atlas">
          <Shell />
        </ErrorBoundary>
      ) : null}
      </div>
      {intro && (
        <FirstLaunch
          key={intro}
          mode={intro}
          onDone={() => (intro === "first" ? setIntroAtStartup(false) : setIntroReplay(false))}
        />
      )}
      {!splashGone && <Splash leaving={ready} />}
      <Toaster
        position="bottom-center"
        toastOptions={{
          style: { background: "var(--bg-3)", color: "var(--text-1)", border: "1px solid var(--line-2)", fontFamily: "var(--font-body)" },
        }}
      />
    </RadixTooltip.Provider>
  );
}
