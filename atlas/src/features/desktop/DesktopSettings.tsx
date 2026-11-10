import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge, Button, Kbd, Panel, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { Settings } from "@/lib/schemas";
import { shortcutFromEvent, shortcutParts } from "./shortcut";

function Row({ title, desc, children }: { title: string; desc?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-4 border-b border-line-1 py-4 last:border-0">
      <div className="min-w-0 flex-1 basis-72">
        <p className="text-sm font-medium text-text-1">{title}</p>
        {desc && <p className="mt-0.5 text-xs text-text-3">{desc}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/** Settings → Desktop: tray, the global shortcut and notifications. Everything here can be turned off. */
export function DesktopSettingsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const d = s.desktop;
  const n = d.notifications;
  const status = useAtlasQuery("desktop-status", api.desktopStatus, ["settings"]);
  const st = status.data;
  const [capturing, setCapturing] = useState(false);
  const set = (patch: Partial<Settings["desktop"]>) => save({ ...s, desktop: { ...d, ...patch } });
  const setN = (patch: Partial<Settings["desktop"]["notifications"]>) => set({ notifications: { ...n, ...patch } });

  // Capture the next key combination as the new shortcut. Esc cancels.
  useEffect(() => {
    if (!capturing) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (e.key === "Escape") return setCapturing(false);
      const combo = shortcutFromEvent(e);
      if (!combo) return; // still holding only modifiers
      setCapturing(false);
      void set({ shortcut: combo });
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capturing]);

  const test = async () => {
    try {
      const r = await api.notificationTest();
      if (r.shown_by_system) toast.success("Sent. If nothing appeared, check that your system allows notifications from ATLAS Co-Pilot.");
      else toast.error("The system did not accept the notification.");
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "The test notification could not be sent");
    }
  };

  return (
    <div className="mt-6 flex flex-col gap-6" data-desktop-settings>
      <Panel className="px-5">
        <Row title="Tray icon" desc={st && !st.tray_supported ? "This system has no tray Atlas can use." : "Shows Atlas near the clock, with Open, Talk and Quit."}>
          <Switch checked={d.tray} label="Tray icon" disabled={st ? !st.tray_supported : false} onChange={(tray) => void set({ tray })} />
        </Row>
        <Row title="Keep running when the window is closed" desc="Closing the window hides Atlas in the tray instead of quitting. Quit from the tray menu. Needs the tray icon.">
          <Switch checked={d.close_to_tray && d.tray} label="Keep running in the tray" disabled={!d.tray || (st ? !st.tray_visible && !d.tray : false)} onChange={(close_to_tray) => void set({ close_to_tray })} />
        </Row>
      </Panel>

      <Panel className="px-5">
        <Row
          title="Summon Atlas from anywhere"
          desc={
            <>
              A system-wide shortcut that brings Atlas forward, ready for you to type. Off until you turn it on.
              {d.shortcut_enabled && st?.shortcut_error && (
                <span className="mt-1 block text-warn" role="alert" data-shortcut-error>
                  {st.shortcut_error}
                </span>
              )}
              {d.shortcut_enabled && st?.shortcut_registered && (
                <span className="mt-1 block text-ok" data-shortcut-active>
                  Active.
                </span>
              )}
            </>
          }
        >
          <Switch checked={d.shortcut_enabled} label="Global shortcut" onChange={(shortcut_enabled) => void set({ shortcut_enabled })} />
        </Row>
        <Row title="Shortcut" desc="Needs Ctrl, Alt or the Windows key. Combinations the system already uses are refused.">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1" aria-label={`Current shortcut: ${shortcutParts(d.shortcut).join(" plus ")}`} data-shortcut-value={d.shortcut}>
              {shortcutParts(d.shortcut).map((p) => (
                <Kbd key={p}>{p}</Kbd>
              ))}
            </span>
            <Button size="sm" onClick={() => setCapturing((c) => !c)} aria-pressed={capturing}>
              {capturing ? "Press the keys… (Esc cancels)" : "Change…"}
            </Button>
          </div>
        </Row>
        <Row title="Start listening when summoned" desc="After the shortcut brings Atlas forward, the microphone turns on (voice must be set up). Otherwise the message box is focused.">
          <Switch checked={d.shortcut_starts_listening} label="Start listening when summoned" onChange={(shortcut_starts_listening) => void set({ shortcut_starts_listening })} />
        </Row>
      </Panel>

      <Panel className="px-5">
        <Row title="System notifications" desc="Atlas always keeps its own list (the bell). Turn this on to also get notifications from your operating system. Off until you turn it on.">
          <Switch checked={n.system} label="System notifications" onChange={(system) => void setN({ system })} />
        </Row>
        <Row title="Only when Atlas isn't in front" desc="Stay quiet while you're looking at Atlas.">
          <Switch checked={n.only_when_away} label="Only when Atlas isn't in front" disabled={!n.system} onChange={(only_when_away) => void setN({ only_when_away })} />
        </Row>
        <Row title="Show what it's about" desc="Include the conversation or mission title. Off shows only “Open Atlas to see it”, because notifications can appear on a lock screen.">
          <Switch checked={n.show_details} label="Show details in notifications" disabled={!n.system} onChange={(show_details) => void setN({ show_details })} />
        </Row>
        <Row title="Notify me about" desc="Applies to system notifications. Failures and approvals always stay visible inside Atlas.">
          <div className="flex flex-col items-end gap-2 text-xs text-text-2">
            {(
              [
                ["approvals", "Approvals Atlas is waiting for"],
                ["replies", "Replies that finish while I'm away"],
                ["missions", "Missions that need me or are ready"],
                ["errors", "Failures"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-3">
                {label}
                <Switch checked={n[key]} label={label} disabled={!n.system} onChange={(v) => void setN({ [key]: v })} />
              </label>
            ))}
          </div>
        </Row>
        <Row title="Test" desc="Sends one notification now.">
          <Button size="sm" onClick={() => void test()} disabled={!n.system}>
            Send a test notification
          </Button>
        </Row>
      </Panel>

      {st && st.notes.length > 0 && (
        <Panel className="px-5 py-4" data-desktop-notes>
          <p className="text-sm font-medium text-text-1">
            On this system <Badge tone="neutral">{st.platform}</Badge>
          </p>
          <ul className="mt-2 list-disc pl-5 text-xs text-text-3">
            {st.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
