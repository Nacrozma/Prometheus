import { SiblingsPage } from "@/features/siblings/Siblings";
import { FocusBar, FocusDialog } from "@/features/focus/Focus";
import { ForgePage } from "@/features/forge/Forge";
import { lazy, Suspense, useEffect } from "react";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Spinner } from "@/components/ui/primitives";
import { CompanionPage } from "@/features/companion/Companion";
import { FilesPage } from "@/features/files/Files";
import { HomePage } from "@/features/home/Home";
import { IntegrationsPage } from "@/features/integrations/Integrations";
import { MemoryPage } from "@/features/memory/Memory";
import { MissionControlPage } from "@/features/mission-control/MissionControl";
import { ProjectsPage } from "@/features/projects/Projects";
import { SettingsPage } from "@/features/settings/Settings";
import { TasksPage } from "@/features/tasks/Tasks";
import { VoicePage } from "@/features/voice/Voice";
import { PresenceProvider } from "@/features/desktop/PresenceProvider";
import { VoiceProvider } from "@/features/voice/VoiceProvider";
import { useUi } from "@/state/ui";
import { ApprovalDock } from "./ApprovalDock";
import { CommandPalette, newConversation } from "./CommandPalette";
import { NAV, Rail } from "./Rail";

// The map pulls in the graph library; load it on first visit.
const AtlasMapPage = lazy(() => import("@/features/atlas-map/AtlasMap").then((m) => ({ default: m.AtlasMapPage })));

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      const ui = useUi.getState();
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.setPalette(!ui.paletteOpen);
      } else if (mod && e.key.toLowerCase() === "n" && !e.shiftKey) {
        e.preventDefault();
        void newConversation();
      } else if (mod && e.key === ",") {
        e.preventDefault();
        ui.navigate("settings");
      } else if (mod && /^[1-9]$/.test(e.key)) {
        const n = NAV.find((x) => x.shortcut === e.key);
        if (n) {
          e.preventDefault();
          ui.navigate(n.route);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function Shell() {
  const route = useUi((s) => s.route);
  useShortcuts();
  return (
    <div className="flex h-full bg-bg-1">
      <a href="#main" className="sr-only-focusable fixed left-2 top-2 z-50 rounded-md bg-accent px-3 py-2 text-text-inverse">
        Skip to content
      </a>
      <Rail />
      <main id="main" className="atmosphere relative min-w-0 flex-1 overflow-hidden" tabIndex={-1}>
        <ErrorBoundary key={route} label={NAV.find((n) => n.route === route)?.label ?? "Settings"}>
        <div className="h-full anim-fade">
          {route === "home" && <HomePage />}
          {route === "companion" && <CompanionPage />}
          {route === "tasks" && <TasksPage />}
          {route === "map" && (
            <Suspense fallback={<div className="grid h-full place-items-center"><Spinner label="Loading the Atlas Map" /></div>}>
              <AtlasMapPage />
            </Suspense>
          )}
          {route === "forge" && <ForgePage />}
          {route === "siblings" && <SiblingsPage />}
          {route === "mission" && <MissionControlPage />}
          {route === "projects" && <ProjectsPage />}
          {route === "memory" && <MemoryPage />}
          {route === "files" && <FilesPage />}
          {route === "integrations" && <IntegrationsPage />}
          {route === "voice" && <VoicePage />}
          {route === "settings" && <SettingsPage />}
        </div>
        </ErrorBoundary>
      </main>
      <ApprovalDock />
      <CommandPalette />
      <VoiceProvider />
      <PresenceProvider />
      <FocusBar />
      <FocusDialog />
    </div>
  );
}
