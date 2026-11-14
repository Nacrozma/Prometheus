import { create } from "zustand";

export type Route =
  | "home"
  | "companion"
  | "tasks"
  | "map"
  | "forge"
  | "siblings"
  | "mission"
  | "projects"
  | "memory"
  | "files"
  | "vault"
  | "integrations"
  | "voice"
  | "settings";

export type SettingsSection =
  | "companion"
  | "voice"
  | "desktop"
  | "schedule"
  | "models"
  | "routing"
  | "forge"
  | "siblings"
  | "permissions"
  | "memory"
  | "appearance"
  | "files"
  | "limits"
  | "usage"
  | "data"
  | "diagnostics"
  | "shortcuts"
  | "about";

interface UiState {
  route: Route;
  settingsSection: SettingsSection;
  paletteOpen: boolean;
  activeConversationId: string | null;
  focusTaskId: string | null;
  focusMapNode: string | null;
  forgeProjectId: string | null;
  /** A task to open on the Tasks page (from a reminder). */
  focusTodoId: string | null;
  openTodo: (id: string | null) => void;
  /** A Knowledge Vault document to open in the reader, at a passage when given (a citation). */
  vaultOpen: { documentId: string; chunkId: string | null; page: number | null; heading: string } | null;
  openVaultSource: (target: { documentId: string; chunkId: string | null; page: number | null; heading: string } | null) => void;
  setForgeProject: (id: string | null) => void;
  navigate: (route: Route) => void;
  openSettings: (section: SettingsSection) => void;
  openConversation: (id: string | null) => void;
  openTask: (id: string) => void;
  openMapNode: (id: string) => void;
  setPalette: (open: boolean) => void;
  /** Play the introduction again (from Settings → About). Not persisted. */
  introReplay: boolean;
  setIntroReplay: (on: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  route: "home",
  settingsSection: "companion",
  paletteOpen: false,
  activeConversationId: null,
  focusTaskId: null,
  focusMapNode: null,
  forgeProjectId: null,
  focusTodoId: null,
  openTodo: (focusTodoId) => set({ route: "tasks", focusTodoId, paletteOpen: false }),
  vaultOpen: null,
  openVaultSource: (vaultOpen) => set(vaultOpen ? { route: "vault", vaultOpen, paletteOpen: false } : { vaultOpen: null }),
  introReplay: false,
  setIntroReplay: (introReplay) => set({ introReplay }),
  setForgeProject: (forgeProjectId) => set({ forgeProjectId }),
  navigate: (route) => set({ route, paletteOpen: false }),
  openSettings: (settingsSection) => set({ route: "settings", settingsSection, paletteOpen: false }),
  openConversation: (activeConversationId) => set({ route: "companion", activeConversationId, paletteOpen: false }),
  openTask: (focusTaskId) => set({ route: "mission", focusTaskId, paletteOpen: false }),
  openMapNode: (focusMapNode) => set({ route: "map", focusMapNode, paletteOpen: false }),
  setPalette: (paletteOpen) => set({ paletteOpen }),
}));
