import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { beforeEach, describe, expect, it, vi } from "vitest";

const notifications = vi.fn();
const markRead = vi.fn().mockResolvedValue(null);
const clear = vi.fn().mockResolvedValue(null);
vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    notifications: () => notifications(),
    notificationsMarkRead: (o: unknown) => markRead(o),
    notificationsClear: () => clear(),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));
vi.mock("@tauri-apps/api/event", () => ({ listen: () => Promise.resolve(() => {}) }));
const startListening = vi.fn().mockResolvedValue(undefined);
let voiceState: Record<string, unknown> = {};
vi.mock("@/state/voice", () => ({ useVoice: { getState: () => ({ startListening, ...voiceState }) } }));
vi.mock("@/features/voice/audioEngine", () => ({ audio: { context: vi.fn() } }));

const { shortcutFromEvent, shortcutParts } = await import("@/features/desktop/shortcut");
const { NotificationBell, openTarget } = await import("@/features/desktop/NotificationBell");
const { onSummon } = await import("@/features/desktop/PresenceProvider");
const { useUi } = await import("@/state/ui");

const key = (o: Partial<KeyboardEvent>) => ({ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, code: "", key: "", ...o });

describe("shortcut capture", () => {
  it("builds a shortcut from a key press and ignores modifier-only presses", () => {
    expect(shortcutFromEvent(key({ ctrlKey: true, altKey: true, code: "Space" }))).toBe("Ctrl+Alt+Space");
    expect(shortcutFromEvent(key({ ctrlKey: true, shiftKey: true, code: "KeyK" }))).toBe("Ctrl+Shift+K");
    expect(shortcutFromEvent(key({ metaKey: true, altKey: true, code: "F9" }))).toBe("Alt+Super+F9");
    expect(shortcutFromEvent(key({ altKey: true, code: "ArrowUp" }))).toBe("Alt+Up");
    expect(shortcutFromEvent(key({ ctrlKey: true, code: "ControlLeft" }))).toBeNull();
    expect(shortcutFromEvent(key({ code: "KeyA" }))).toBeNull();
    expect(shortcutFromEvent(key({ ctrlKey: true, code: "F25" }))).toBeNull();
    expect(shortcutParts("Ctrl+Super+A")).toEqual(["Ctrl", "Win", "A"]);
  });
});

describe("notification bell", () => {
  beforeEach(() => {
    markRead.mockClear();
    clear.mockClear();
    useUi.setState({ route: "home", activeConversationId: null });
  });

  it("shows the unread count, lists what happened and opens what a notice is about", async () => {
    notifications.mockResolvedValue({
      unread: 2,
      items: [
        { id: "n1", category: "approval", title: "Atlas needs your approval", detail: "Create notes.md", target: "approvals", created_at: new Date().toISOString(), read_at: null, shown_by_system: false },
        { id: "n2", category: "reply", title: "Atlas has replied", detail: "Trip plan", target: "conversation:c9", created_at: new Date().toISOString(), read_at: null, shown_by_system: true },
        { id: "n3", category: "mission", title: "A mission is ready for your review", detail: "", target: "mission:m1", created_at: "2026-01-01T00:00:00Z", read_at: "2026-01-01T00:01:00Z", shown_by_system: false },
      ],
    });
    render(<TooltipProvider><NotificationBell /></TooltipProvider>);
    const bell = await screen.findByRole("button", { name: "Notifications (2 unread)" });
    expect(bell.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(bell);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeTruthy();
    expect(screen.getByText("Atlas needs your approval")).toBeTruthy();
    fireEvent.click(screen.getByText("Atlas has replied"));
    expect(markRead).toHaveBeenCalledWith({ id: "n2" });
    expect(useUi.getState().route).toBe("companion");
    expect(useUi.getState().activeConversationId).toBe("c9");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("has an honest empty state, closes on Escape, and can mark all read or clear", async () => {
    notifications.mockResolvedValue({ unread: 0, items: [] });
    render(<TooltipProvider><NotificationBell /></TooltipProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(screen.getByText(/Nothing yet/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Mark all read" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("routes each kind of target", () => {
    openTarget("approvals");
    expect(useUi.getState().route).toBe("mission");
    openTarget("mission:m1");
    expect(useUi.getState().route).toBe("siblings");
    openTarget("");
    expect(useUi.getState().route).toBe("siblings");
  });
});

describe("summoning Atlas", () => {
  beforeEach(() => {
    startListening.mockClear();
    document.body.innerHTML = '<textarea id="composer"></textarea>';
    useUi.setState({ route: "memory", paletteOpen: true });
  });

  it("opens the Companion with the message box focused, without starting the microphone", () => {
    voiceState = { settings: { enabled: true }, status: { stt_ready: true }, capture: "off" };
    onSummon(false);
    expect(useUi.getState().route).toBe("companion");
    expect(useUi.getState().paletteOpen).toBe(false);
    expect(document.activeElement?.id).toBe("composer");
    expect(startListening).not.toHaveBeenCalled();
  });

  it("starts listening only when asked and voice is ready; otherwise it focuses the box", () => {
    voiceState = { settings: { enabled: true }, status: { stt_ready: true }, capture: "off" };
    onSummon(true);
    expect(startListening).toHaveBeenCalledTimes(1);
    startListening.mockClear();
    voiceState = { settings: { enabled: false }, status: { stt_ready: true }, capture: "off" };
    onSummon(true);
    voiceState = { settings: { enabled: true }, status: { stt_ready: true }, capture: "listening" };
    onSummon(true);
    expect(startListening).not.toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("composer");
  });

  it("never interrupts the introduction", () => {
    document.body.innerHTML = '<div data-first-launch="first"></div><textarea id="composer"></textarea>';
    voiceState = { settings: { enabled: true }, status: { stt_ready: true }, capture: "off" };
    onSummon(true);
    expect(useUi.getState().route).toBe("memory");
    expect(startListening).not.toHaveBeenCalled();
  });
});
