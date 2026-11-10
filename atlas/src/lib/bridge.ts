/**
 * Typed bridge to the trusted core. The UI never handles secrets beyond passing a newly typed
 * key once to `setProviderKey`; nothing here can read a stored key back.
 */
import { Channel, invoke } from "@tauri-apps/api/core";
import { z } from "zod";
import * as S from "./schemas";

export class AtlasError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "AtlasError";
  }
}

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function toAtlasError(e: unknown): AtlasError {
  const parsed = S.AppErrorSchema.safeParse(e);
  if (parsed.success) return new AtlasError(parsed.data.code, parsed.data.message);
  if (e instanceof Error) return new AtlasError("internal", e.message);
  return new AtlasError("internal", typeof e === "string" ? e : "Unexpected error");
}

async function call<T extends z.ZodType>(cmd: string, args: Record<string, unknown>, schema: T): Promise<z.infer<T>> {
  let raw: unknown;
  try {
    raw = await invoke(cmd, args);
  } catch (e) {
    throw toAtlasError(e);
  }
  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    console.error(`[atlas] ${cmd} returned an unexpected shape`, parsed.error.issues);
    throw new AtlasError("contract", `Atlas received an unexpected response from "${cmd}".`);
  }
  return parsed.data;
}

const Void = z.null();
const Opt = <T extends z.ZodType>(t: T) => t.nullable();

export const api = {
  appInfo: () => call("app_info", {}, S.AppInfoSchema),
  diagnostics: () => call("diagnostics", {}, z.record(z.string(), z.unknown())),
  recentErrors: (limit = 30) => call("recent_errors", { limit }, z.array(S.AuditEventSchema)),
  openExternal: (url: string) => call("open_external", { url }, Void),
  saveTextViaDialog: (suggestedName: string, extension: "json" | "md" | "txt" | "csv", content: string) =>
    call("save_text_via_dialog", { suggestedName, extension, content }, Opt(z.string())),

  desktopStatus: () => call("desktop_status", {}, S.DesktopStatusSchema),
  notifications: (limit = 50) => call("notifications_list", { limit }, S.NotificationListSchema),
  notificationsMarkRead: (opts: { id?: string; target?: string } = {}) => call("notifications_mark_read", { id: opts.id ?? null, target: opts.target ?? null }, Void),
  notificationsClear: () => call("notifications_clear", {}, Void),
  notificationTest: () => call("notification_test", {}, S.NotificationSchema),
  windowHide: () => call("window_hide", {}, Void),

  voiceStatus: () => call("voice_status", {}, S.VoiceStatusSchema),
  voiceInstall: (id: string, onProgress: (p: S.DownloadProgress) => void) => {
    const channel = new Channel<unknown>();
    channel.onmessage = (raw) => {
      const parsed = S.DownloadProgressSchema.safeParse(raw);
      if (parsed.success) onProgress(parsed.data);
    };
    return call("voice_install", { id, onProgress: channel }, S.VoiceStatusSchema);
  },
  voiceInstallCancel: (id: string) => call("voice_install_cancel", { id }, z.boolean()),
  voiceRemove: (id: string) => call("voice_remove", { id }, S.VoiceStatusSchema),
  voiceVerify: (id: string) => call("voice_verify", { id }, z.array(z.string())),
  /** WAV bytes for playback. */
  voiceSynthesize: async (text: string, speed?: number): Promise<ArrayBuffer> => {
    try {
      const out = await invoke<ArrayBuffer | number[]>("voice_synthesize", { text, speed: speed ?? null });
      return out instanceof ArrayBuffer ? out : new Uint8Array(out).buffer;
    } catch (e) {
      throw toAtlasError(e);
    }
  },
  voiceStopSpeech: () => call("voice_stop_speech", {}, Void),
  /** Send a 16-bit PCM recording as raw bytes; it is transcribed in memory and discarded. */
  voiceTranscribe: async (pcm: Int16Array, sampleRate: number) => {
    let raw: unknown;
    try {
      raw = await invoke("voice_transcribe", new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength), { headers: { "x-sample-rate": String(sampleRate) } });
    } catch (e) {
      throw toAtlasError(e);
    }
    const parsed = S.TranscriptSchema.safeParse(raw);
    if (!parsed.success) throw new AtlasError("contract", "Atlas received an unexpected transcription result.");
    return parsed.data;
  },
  voiceCancelTranscription: () => call("voice_cancel_transcription", {}, z.boolean()),
  voiceBenchmark: () => call("voice_benchmark", {}, S.BenchmarkSchema),
  settings: () => call("settings_get", {}, S.SettingsSchema),
  updateSettings: (settings: S.Settings) => call("settings_update", { settings }, S.SettingsSchema),
  /** Record that the one-time introduction finished or was skipped (idempotent). */
  completeFirstLaunch: () => call("first_launch_complete", {}, S.SettingsSchema),
  pickWorkspace: () => call("workspace_pick", {}, Opt(S.SettingsSchema)),
  useDefaultWorkspace: () => call("workspace_use_default", {}, S.SettingsSchema),
  addSampleFile: () => call("workspace_add_sample", {}, z.string()),
  browseWorkspace: (path?: string) => call("workspace_browse", { path: path ?? null }, S.WorkspaceListingSchema),
  previewWorkspaceFile: (path: string) =>
    call(
      "workspace_preview",
      { path },
      z.object({
        path: z.string(),
        content: z.string().optional(),
        bytes: z.number().optional(),
        truncated: z.boolean().optional(),
        error: z.string().optional(),
        code: z.string().optional(),
      }),
    ),
  revealWorkspace: (path?: string) => call("workspace_reveal", { path: path ?? null }, Void),

  providerTemplates: () => call("provider_templates", {}, z.array(S.ProviderTemplateSchema)),
  providers: () => call("providers_list", {}, z.array(S.ProviderConfigSchema)),
  addProvider: (p: { kind: S.ProviderKind; label: string; baseUrl: string; defaultModel: string | null }) =>
    call("provider_add", { provider: p }, S.ProviderConfigSchema),
  updateProvider: (id: string, label: string, baseUrl: string, defaultModel: string | null, enabled: boolean) =>
    call("provider_update", { id, label, baseUrl, defaultModel, enabled }, S.ProviderConfigSchema),
  deleteProvider: (id: string) => call("provider_delete", { id }, Void),
  setProviderKey: (id: string, key: string) => call("provider_set_key", { id, key }, S.ProviderConfigSchema),
  clearProviderKey: (id: string) => call("provider_clear_key", { id }, S.ProviderConfigSchema),
  testProvider: (id: string) => call("provider_test", { id }, S.ProviderTestResultSchema),

  integrations: () => call("integrations_list", {}, z.array(S.IntegrationSchema)),
  setIntegrationKey: (id: string, key: string) => call("integration_set_key", { id, key }, S.IntegrationSchema),
  clearIntegrationKey: (id: string) => call("integration_clear_key", { id }, S.IntegrationSchema),
  setIntegrationEnabled: (id: string, enabled: boolean) =>
    call("integration_set_enabled", { id, enabled }, S.IntegrationSchema),
  testIntegration: (id: string) => call("integration_test", { id }, S.IntegrationSchema),
  tools: () => call("tools_list", {}, z.array(S.ToolInfoSchema)),
  setToolEnabled: (id: string, enabled: boolean) => call("tool_set_enabled", { id, enabled }, Void),

  conversations: (opts: { projectId?: string | null; includeArchived?: boolean; limit?: number; offset?: number } = {}) =>
    call(
      "conversations_list",
      {
        projectId: opts.projectId ?? null,
        includeArchived: opts.includeArchived ?? false,
        limit: opts.limit ?? 200,
        offset: opts.offset ?? 0,
      },
      z.array(S.ConversationSchema),
    ),
  createConversation: (projectId: string | null, title?: string) =>
    call("conversation_create", { projectId, title: title ?? null }, S.ConversationSchema),
  messages: (id: string) => call("conversation_messages", { id }, z.array(S.MessageSchema)),
  renameConversation: (id: string, title: string) => call("conversation_rename", { id, title }, Void),
  archiveConversation: (id: string, archived: boolean) => call("conversation_archive", { id, archived }, Void),
  moveConversation: (id: string, projectId: string | null) => call("conversation_move", { id, projectId }, Void),
  deleteConversation: (id: string) => call("conversation_delete", { id }, Void),
  searchConversations: (query: string) => call("conversations_search", { query }, z.array(S.SearchHitSchema)),
  exportConversation: (id: string) => call("conversation_export", { id }, Opt(z.string())),

  /** Stream a turn. `onEvent` receives validated events; malformed events are dropped and logged. */
  send: (
    params: { conversationId: string; text: string; providerId?: string | null; model?: string | null; budgetOverride?: boolean; regenerate?: boolean },
    onEvent: (e: S.TurnEvent) => void,
  ) => {
    const channel = new Channel<unknown>();
    channel.onmessage = (raw) => {
      const parsed = S.TurnEventSchema.safeParse(raw);
      if (parsed.success) onEvent(parsed.data);
      else console.error("[atlas] malformed turn event", parsed.error.issues);
    };
    return call(
      "chat_send",
      {
        params: {
          conversationId: params.conversationId,
          text: params.text,
          providerId: params.providerId ?? null,
          model: params.model ?? null,
          budgetOverride: params.budgetOverride ?? false,
          regenerate: params.regenerate ?? false,
        },
        onEvent: channel,
      },
      S.TurnSummarySchema,
    );
  },
  cancel: (conversationId: string) => call("chat_cancel", { conversationId }, z.boolean()),

  pendingApprovals: () => call("approvals_pending", {}, z.array(S.ApprovalSchema)),
  decideApproval: (id: string, approve: boolean) => call("approval_decide", { id, approve }, Void),
  tasks: (status?: string | null, limit = 200) => call("tasks_list", { status: status ?? null, limit }, z.array(S.TaskSchema)),
  taskDetail: (id: string) => call("task_detail", { id }, S.TaskDetailSchema),
  cancelTask: (id: string) => call("task_cancel", { id }, z.boolean()),
  dismissTask: (id: string) => call("task_dismiss", { id }, Void),
  retryStep: (stepId: string) => call("task_retry_step", { stepId }, z.unknown()),
  emergencyStop: () => call("emergency_stop", {}, z.number()),
  activeTurns: () =>
    call(
      "active_turns",
      {},
      z.array(z.object({ turn_id: z.string(), conversation_id: z.string(), started_at: z.string(), task_id: z.string().nullable() })),
    ),

  memories: (scope: "all" | "global" | string = "all") => call("memories_list", { scope }, z.array(S.MemorySchema)),
  createMemory: (m: { projectId: string | null; kind: S.MemoryKind; content: string; pinned?: boolean }) =>
    call("memory_create", { projectId: m.projectId, kind: m.kind, content: m.content, pinned: m.pinned ?? false }, S.MemorySchema),
  updateMemory: (
    id: string,
    patch: { content?: string; kind?: S.MemoryKind; pinned?: boolean; projectId?: string | null },
  ) => call("memory_update", { id, patch }, S.MemorySchema),
  deleteMemory: (id: string) => call("memory_delete", { id }, Void),
  deleteAllMemories: (confirm: string) => call("memory_delete_all", { confirm }, z.number()),
  searchMemories: (query: string, projectId?: string | null) =>
    call("memory_search", { query, projectId: projectId ?? null }, z.array(S.RetrievedSchema)),
  exportMemories: () => call("memory_export", {}, Opt(z.string())),

  projects: (includeArchived = true) => call("projects_list", { includeArchived }, z.array(S.ProjectSchema)),
  createProject: (name: string, description: string, instructions: string) =>
    call("project_create", { name, description, instructions }, S.ProjectSchema),
  updateProject: (id: string, name: string, description: string, instructions: string, archived: boolean) =>
    call("project_update", { id, name, description, instructions, archived }, S.ProjectSchema),
  deleteProject: (id: string) => call("project_delete", { id }, Void),
  exportProject: (id: string) => call("project_export", { id }, Opt(z.string())),

  shareFile: () => call("file_share_pick", {}, Opt(S.GrantSchema)),
  grants: () => call("grants_list", {}, z.array(S.GrantSchema)),
  revokeGrant: (id: string) => call("grant_revoke", { id }, Void),

  usage: () => call("usage_summary", {}, S.UsageSummarySchema),
  graph: () => call("map_graph", {}, S.GraphSchema),

  exportAll: () => call("export_all", {}, Opt(z.string())),
  backupCreate: () => call("backup_create", {}, Opt(z.string())),
  backupInspect: () => call("backup_inspect", {}, Opt(z.record(z.string(), z.unknown()))),
  backupRestoreConfirm: () => call("backup_restore_confirm", {}, Void),
  removeAllCredentials: (confirm: string) => call("credentials_remove_all", { confirm }, Void),
  pricingSchedule: () => call("pricing_schedule", {}, S.PricingScheduleSchema),

  forgeProjects: () => call("forge_projects", {}, z.array(S.ForgeProjectSchema)),
  forgePickProject: (testCommand: string | null) => call("forge_project_pick", { testCommand }, Opt(S.ForgeProjectSchema)),
  forgeUpdateProject: (id: string, name: string, testCommand: string | null, buildCommand: string | null) =>
    call("forge_project_update", { id, name, testCommand, buildCommand }, S.ForgeProjectSchema),
  forgeRemoveProject: (id: string) => call("forge_project_remove", { id }, Void),
  forgeTree: (projectId: string, path: string, depth = 1) => call("forge_tree", { projectId, path, depth }, S.ForgeTreeSchema),
  forgeReadFile: (projectId: string, path: string) => call("forge_read_file", { projectId, path }, z.object({ path: z.string(), content: z.string() })),
  forgeCreateSession: (projectId: string, discipline: S.Discipline) => call("forge_session_create", { projectId, discipline }, S.ConversationSchema),
  forgeSessions: (projectId: string) => call("forge_sessions", { projectId }, z.array(S.ConversationSchema)),
  forgeSetDiscipline: (conversationId: string, discipline: S.Discipline) => call("forge_set_discipline", { conversationId, discipline }, S.ConversationSchema),
  forgeRun: (projectId: string, command: string) => call("forge_run", { projectId, command }, S.ForgeRunSchema),
  forgeCancelRun: (runId: string) => call("forge_run_cancel", { runId }, z.boolean()),
  forgeRuns: (projectId: string) => call("forge_runs", { projectId }, z.array(S.ForgeRunSchema)),
  forgeGitStatus: (projectId: string) => call("forge_git_status", { projectId }, S.GitStatusSchema),
  forgeGitDiff: (projectId: string, path: string | null) => call("forge_git_diff", { projectId, path }, z.string()),
  forgeGitLog: (projectId: string) => call("forge_git_log", { projectId }, z.array(S.GitCommitSchema)),
  forgeGitCommit: (projectId: string, message: string, paths: string[]) => call("forge_git_commit", { projectId, message, paths }, z.string()),
  forgeGitBranch: (projectId: string, name: string) => call("forge_git_branch", { projectId, name }, Void),
  forgeChanges: (projectId: string) => call("forge_changes", { projectId }, z.array(S.ForgeChangeSchema)),
  forgeChangeDiff: (changeId: string) => call("forge_change_diff", { changeId }, z.string()),
  forgeRevert: (changeId: string) => call("forge_revert", { changeId }, S.ForgeChangeSchema),

  siblings: () => call("siblings_list", {}, z.array(S.SiblingSchema)),
  pairSibling: (endpoint: string, code: string) => call("sibling_pair", { endpoint, code }, S.SiblingSchema),
  refreshSibling: (id: string) => call("sibling_refresh", { id }, S.SiblingSchema),
  revokeSibling: (id: string) => call("sibling_revoke", { id }, S.SiblingSchema),
  forgetSibling: (id: string) => call("sibling_forget", { id }, Void),
  missions: () => call("missions_list", {}, z.array(S.MissionSchema)),
  missionDetail: (id: string) => call("mission_detail", { id }, S.MissionDetailSchema),
  createMission: (m: { title: string; mode: S.MissionMode; objective: string; sharedContext: string; siblingId: string | null; forgeProjectId: string | null; conversationId: string | null }) =>
    call("mission_create", { mission: m }, S.MissionSchema),
  updateMission: (id: string, title: string, objective: string, sharedContext: string, siblingId: string | null) =>
    call("mission_update", { id, title, objective, sharedContext, siblingId }, S.MissionSchema),
  missionTransition: (id: string, to: S.MissionState) => call("mission_transition", { id, to }, S.MissionSchema),
  sendMission: (id: string) => call("mission_send", { id }, S.MissionSchema),
  missionMessage: (id: string, text: string) => call("mission_message", { id, text }, S.MissionSchema),
  acceptMission: (id: string, note: string) => call("mission_accept", { id, note }, S.MissionSchema),
  cancelMission: (id: string) => call("mission_cancel", { id }, S.MissionSchema),
  syncMission: (id: string) => call("mission_sync", { id }, S.MissionSchema),
  missionNote: (id: string, text: string) => call("mission_note", { id, text }, Void),
};

export type Api = typeof api;
