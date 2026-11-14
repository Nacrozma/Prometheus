/**
 * Zod schemas for every payload crossing the IPC boundary. Field names match the Rust serde
 * output (snake_case). Inferred types are exported for the UI.
 */
import { z } from "zod";

export const AppErrorSchema = z.object({ code: z.string(), message: z.string() });
export type AppErrorShape = z.infer<typeof AppErrorSchema>;

// ---------- settings ----------
const gate = z.enum(["ask", "allow"]);
export const RoutingModeSchema = z.enum(["auto", "budget", "balanced", "quality", "manual"]);
export type RoutingMode = z.infer<typeof RoutingModeSchema>;
export const TierSchema = z.enum(["fast", "standard", "heavy"]);
export type Tier = z.infer<typeof TierSchema>;
export const TierModelSchema = z.object({ provider_id: z.string(), model: z.string() });
export type TierModel = z.infer<typeof TierModelSchema>;
export const PriceOverrideSchema = z.object({ model: z.string(), input_per_mtok: z.number(), output_per_mtok: z.number() });
export type PriceOverride = z.infer<typeof PriceOverrideSchema>;
export const SettingsSchema = z.object({
  onboarding_completed: z.boolean(),
  companion: z.object({
    preferred_name: z.string(),
    tone: z.enum(["warm", "balanced", "precise"]),
    verbosity: z.enum(["concise", "balanced", "detailed"]),
    proactivity: z.enum(["reserved", "balanced", "proactive"]),
    effort: z.enum(["low", "medium", "high"]),
    show_reasoning_summary: z.boolean(),
    personality: z.enum(["professional", "friendly", "analytical", "concise", "detailed", "creative", "custom"]),
    custom_instructions: z.string(),
  }),
  default_provider_id: z.string().nullable(),
  default_model: z.string().nullable(),
  routing: z.object({
    allow_cross_provider_fallback: z.boolean(),
    anthropic_refusal_fallback: z.boolean(),
    mode: RoutingModeSchema,
    fast: TierModelSchema.nullable(),
    standard: TierModelSchema.nullable(),
    heavy: TierModelSchema.nullable(),
  }),
  permissions: z.object({ local_write: gate, network_tools: gate, planner: gate.default("allow") }),
  memory: z.object({ enabled: z.boolean(), max_retrieved: z.number() }),
  vault: z.object({ use_in_chat: z.boolean(), local_only: z.boolean(), max_passages: z.number() }).default({ use_in_chat: true, local_only: false, max_passages: 4 }),
  workspace_dir: z.string().nullable(),
  appearance: z.object({
    theme: z.enum(["dark", "light", "system"]),
    motion: z.enum(["system", "reduced", "full"]),
    font_scale: z.number(),
  }),
  limits: z.object({
    max_model_steps: z.number(),
    max_tool_calls: z.number(),
    request_timeout_secs: z.number(),
    tool_timeout_secs: z.number(),
    approval_timeout_secs: z.number(),
    max_output_tokens: z.number(),
  }),
  network: z.object({ offline_mode: z.boolean() }),
  retention: z.object({ conversation_days: z.number().nullable(), audit_days: z.number().nullable() }),
  usage: z.object({
    monthly_budget_usd: z.number().nullable(),
    daily_budget_usd: z.number().nullable(),
    per_request_usd: z.number().nullable(),
    mission_budget_usd: z.number().nullable(),
    daily_request_limit: z.number().nullable(),
    warn_at_percent: z.number(),
    on_exceed: z.enum(["stop", "ask"]),
    price_overrides: z.array(PriceOverrideSchema),
  }),
  voice: z.object({
    enabled: z.boolean(),
    speak_responses: z.boolean(),
    language: z.string(),
    tts_voice: z.string().nullable(),
    stt_model: z.string().nullable(),
    speed: z.number(),
    volume: z.number(),
    auto_send: z.boolean(),
    input_device: z.string().nullable(),
    output_device: z.string().nullable().default(null),
  }),
  desktop: z.object({
    tray: z.boolean(),
    close_to_tray: z.boolean(),
    shortcut_enabled: z.boolean(),
    shortcut: z.string(),
    shortcut_starts_listening: z.boolean(),
    notifications: z.object({
      system: z.boolean(),
      only_when_away: z.boolean(),
      show_details: z.boolean(),
      approvals: z.boolean(),
      replies: z.boolean(),
      missions: z.boolean(),
      errors: z.boolean(),
      reminders: z.boolean().default(true),
      deadlines: z.boolean().default(true),
      briefings: z.boolean().default(true),
    }),
  }),
  schedule: z
    .object({ paused: z.boolean(), deadline_notices: z.boolean(), deadline_hour: z.number(), missed_grace_minutes: z.number() })
    .default({ paused: false, deadline_notices: true, deadline_hour: 9, missed_grace_minutes: 720 }),
  briefing: z
    .object({ enabled: z.boolean(), time: z.string(), include_overdue: z.boolean(), include_upcoming: z.boolean(), include_missions: z.boolean(), include_recent: z.boolean() })
    .default({ enabled: false, time: "08:00", include_overdue: true, include_upcoming: true, include_missions: true, include_recent: true }),
  home: z
    .object({ show_briefing: z.boolean(), show_missions: z.boolean(), show_conversations: z.boolean(), show_accomplished: z.boolean(), show_status: z.boolean() })
    .default({ show_briefing: true, show_missions: true, show_conversations: true, show_accomplished: true, show_status: true }),
  default_project_id: z.string().nullable(),
  forge: z.object({ command_timeout_secs: z.number(), max_output_kb: z.number() }),
  first_launch: z.object({ completed_at: z.string().nullable() }),
});
export type Settings = z.infer<typeof SettingsSchema>;
export type Personality = Settings["companion"]["personality"];

// ---------- providers ----------
export const ProviderKindSchema = z.enum(["anthropic", "openai", "openai_compatible", "ollama", "openrouter", "mistral", "cerebras", "mock"]);
export type ProviderKind = z.infer<typeof ProviderKindSchema>;
export const ProviderStatusSchema = z.enum([
  "not_configured",
  "untested",
  "connected",
  "unavailable",
  "auth_failed",
  "rate_limited",
  "degraded",
]);
export type ProviderStatus = z.infer<typeof ProviderStatusSchema>;

export const ModelInfoSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  context_window: z.number().nullable(),
  max_output_tokens: z.number().nullable(),
  supports_tools: z.boolean().nullable(),
  supports_vision: z.boolean().nullable(),
  supports_reasoning: z.boolean().nullable(),
  supports_effort: z.boolean().nullable(),
});
export type ModelInfo = z.infer<typeof ModelInfoSchema>;

export const ProviderConfigSchema = z.object({
  id: z.string(),
  kind: ProviderKindSchema,
  label: z.string(),
  base_url: z.string(),
  default_model: z.string().nullable(),
  enabled: z.boolean(),
  status: ProviderStatusSchema,
  status_detail: z.string().nullable(),
  last_checked_at: z.string().nullable(),
  models: z.array(ModelInfoSchema),
  has_credential: z.boolean(),
  key_hint: z.string().nullable(),
  local: z.boolean(),
});
export type ProviderConfig = z.infer<typeof ProviderConfigSchema>;

export const ProviderTemplateSchema = z.object({
  kind: ProviderKindSchema,
  label: z.string(),
  default_base_url: z.string(),
  suggested_model: z.string(),
  needs_key: z.boolean(),
  local: z.boolean(),
  key_help: z.string(),
  key_placeholder: z.string(),
  optional: z.boolean(),
  privacy_note: z.string(),
});
export type ProviderTemplate = z.infer<typeof ProviderTemplateSchema>;

export const ProviderTestResultSchema = z.object({ provider: ProviderConfigSchema, ok: z.boolean(), message: z.string() });

// ---------- integrations & tools ----------
export const IntegrationSchema = z.object({
  id: z.string(),
  name: z.string(),
  category: z.string(),
  description: z.string(),
  capabilities: z.array(z.string()),
  auth: z.string(),
  permission_scope: z.string(),
  setup: z.string(),
  implemented: z.boolean(),
  enabled: z.boolean(),
  status: z.string(),
  status_detail: z.string().nullable(),
  last_checked_at: z.string().nullable(),
  has_credential: z.boolean(),
  key_hint: z.string().nullable(),
});
export type Integration = z.infer<typeof IntegrationSchema>;

export const PermissionClassSchema = z.enum(["read_only", "local_write", "consequential", "destructive"]);
export type PermissionClass = z.infer<typeof PermissionClassSchema>;
export const AvailabilitySchema = z.discriminatedUnion("state", [
  z.object({ state: z.literal("available") }),
  z.object({ state: z.literal("needs_configuration"), reason: z.string() }),
  z.object({ state: z.literal("unavailable"), reason: z.string() }),
]);
export type Availability = z.infer<typeof AvailabilitySchema>;
export const ToolInfoSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  category: z.string(),
  version: z.string(),
  permission: PermissionClassSchema,
  network: z.boolean(),
  requires: z.array(z.string()),
  timeout_secs: z.number(),
  data_scope: z.string(),
  enabled: z.boolean(),
  availability: AvailabilitySchema,
  use_count: z.number(),
  failure_count: z.number(),
  last_used_at: z.string().nullable(),
});
export type ToolInfo = z.infer<typeof ToolInfoSchema>;

// ---------- conversations ----------
export const PartSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("text"), text: z.string() }),
  z.object({ type: z.literal("tool_call"), id: z.string(), name: z.string(), input: z.unknown() }),
  z.object({ type: z.literal("tool_result"), call_id: z.string(), content: z.string(), is_error: z.boolean() }),
]);
export type Part = z.infer<typeof PartSchema>;

export const ConversationSchema = z.object({
  id: z.string(),
  project_id: z.string().nullable(),
  title: z.string(),
  archived: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  message_count: z.number(),
  forge_project_id: z.string().nullable().optional(),
  discipline: z.lazy(() => DisciplineSchema).nullable().optional(),
});
export type Conversation = z.infer<typeof ConversationSchema>;

export const MessageSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  seq: z.number(),
  role: z.enum(["user", "assistant", "tool", "notice"]),
  content: z.string(),
  parts: z.array(PartSchema).nullable(),
  provider_id: z.string().nullable(),
  model: z.string().nullable(),
  status: z.string(),
  task_id: z.string().nullable(),
  usage: z.unknown().nullable(),
  created_at: z.string(),
});
export type Message = z.infer<typeof MessageSchema>;

export const SearchHitSchema = z.object({
  conversation_id: z.string(),
  conversation_title: z.string(),
  message_id: z.string(),
  snippet: z.string(),
  created_at: z.string(),
});
export type SearchHit = z.infer<typeof SearchHitSchema>;

// ---------- approvals & tasks ----------
export const PreviewSchema = z.object({ action: z.string(), target: z.string(), details: z.string(), consequences: z.string() });
export const ApprovalSchema = z.object({
  id: z.string(),
  task_id: z.string(),
  step_id: z.string(),
  tool_id: z.string(),
  action_hash: z.string(),
  preview: PreviewSchema,
  status: z.string(),
  created_at: z.string(),
  decided_at: z.string().nullable(),
});
export type Approval = z.infer<typeof ApprovalSchema>;

export const TaskStatusSchema = z.enum([
  "created",
  "planning",
  "awaiting_approval",
  "ready",
  "running",
  "verifying",
  "completed",
  "failed",
  "cancelled",
  "interrupted",
  "recoverable",
]);
export type TaskStatus = z.infer<typeof TaskStatusSchema>;
export const TaskSchema = z.object({
  id: z.string(),
  conversation_id: z.string().nullable(),
  request: z.string(),
  status: TaskStatusSchema,
  summary: z.string().nullable(),
  error: z.string().nullable(),
  verification: z.unknown().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  finished_at: z.string().nullable(),
  step_count: z.number(),
});
export type Task = z.infer<typeof TaskSchema>;
export const StepSchema = z.object({
  id: z.string(),
  task_id: z.string(),
  seq: z.number(),
  tool_id: z.string(),
  input: z.unknown(),
  permission: z.string(),
  status: z.string(),
  output: z.unknown().nullable(),
  error: z.string().nullable(),
  approval_id: z.string().nullable(),
  duration_ms: z.number().nullable(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
});
export type Step = z.infer<typeof StepSchema>;
export const TaskDetailSchema = z.object({ task: TaskSchema, steps: z.array(StepSchema), approvals: z.array(ApprovalSchema) });
export type TaskDetail = z.infer<typeof TaskDetailSchema>;

// ---------- streaming turn events ----------
const DispatchEventSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("step_started"), step_id: z.string(), tool_id: z.string(), task_id: z.string() }),
  z.object({ type: z.literal("approval_required"), approval: ApprovalSchema }),
  z.object({ type: z.literal("step_finished"), step_id: z.string(), tool_id: z.string(), status: z.string(), task_id: z.string() }),
]);
export type DispatchEvent = z.infer<typeof DispatchEventSchema>;
export const StopReasonSchema = z.object({ kind: z.string(), category: z.string().nullable().optional(), reason: z.string().optional() });
const UsageSchema = z.object({ input_tokens: z.number().nullable(), output_tokens: z.number().nullable() });
export const TurnEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("started"),
    turn_id: z.string(),
    conversation_id: z.string(),
    user_message_id: z.string(),
    provider_label: z.string(),
    provider_kind: ProviderKindSchema,
    model: z.string(),
    local: z.boolean(),
    route_reason: z.string(),
    fell_back: z.boolean(),
    tier: TierSchema.nullable().optional(),
    memories: z.array(z.object({ id: z.string(), content: z.string(), reason: z.string() })),
    sources: z.lazy(() => z.array(VaultSourceSchema)).default([]),
    tools_offered: z.number(),
  }),
  z.object({ type: z.literal("text_delta"), text: z.string() }),
  z.object({ type: z.literal("reasoning_delta"), text: z.string() }),
  z.object({ type: z.literal("tool_call_started"), call_id: z.string(), name: z.string() }),
  z.object({ type: z.literal("step_reset"), reason: z.string() }),
  z.object({ type: z.literal("tool"), event: DispatchEventSchema }),
  z.object({ type: z.literal("assistant_message"), message_id: z.string(), stop: StopReasonSchema, served_model: z.string() }),
  z.object({ type: z.literal("tool_results"), message_id: z.string() }),
  z.object({ type: z.literal("notice"), level: z.string(), text: z.string() }),
  z.object({ type: z.literal("task_updated"), task_id: z.string(), status: TaskStatusSchema }),
  z.object({
    type: z.literal("finished"),
    outcome: z.string(),
    error: z.string().nullable(),
    usage: UsageSchema,
    estimated_cost_usd: z.number().nullable(),
    task_id: z.string().nullable(),
  }),
]);
export type TurnEvent = z.infer<typeof TurnEventSchema>;
export type StartedEvent = Extract<TurnEvent, { type: "started" }>;

export const TurnSummarySchema = z.object({
  turn_id: z.string(),
  outcome: z.string(),
  task_id: z.string().nullable(),
  error: z.string().nullable(),
});

// ---------- memory & projects ----------
export const MemoryKindSchema = z.enum(["preference", "fact", "note"]);
export type MemoryKind = z.infer<typeof MemoryKindSchema>;
export const MemorySchema = z.object({
  id: z.string(),
  project_id: z.string().nullable(),
  kind: MemoryKindSchema,
  content: z.string(),
  source: z.string(),
  pinned: z.boolean(),
  use_count: z.number(),
  last_used_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Memory = z.infer<typeof MemorySchema>;
export const RetrievedSchema = z.object({ memory: MemorySchema, reason: z.string(), score: z.number() });
export type Retrieved = z.infer<typeof RetrievedSchema>;

export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  instructions: z.string(),
  archived: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  conversation_count: z.number(),
  memory_count: z.number(),
});
export type Project = z.infer<typeof ProjectSchema>;

export const GrantSchema = z.object({ id: z.string(), path: z.string(), label: z.string(), created_at: z.string() });
export type Grant = z.infer<typeof GrantSchema>;

// ---------- usage, map, diagnostics ----------
export const UsageSummarySchema = z.object({
  period_start: z.string(),
  by_model: z.array(
    z.object({
      provider_id: z.string(),
      provider_label: z.string().nullable(),
      model: z.string(),
      requests: z.number(),
      errors: z.number(),
      rate_limited: z.number(),
      input_tokens: z.number(),
      output_tokens: z.number(),
      estimated_cost_usd: z.number(),
      unknown_cost_requests: z.number(),
      avg_duration_ms: z.number().nullable(),
    }),
  ),
  month_estimated_cost_usd: z.number(),
  month_has_unknown_costs: z.boolean(),
  month_unverified_cost_usd: z.number(),
  today_requests: z.number(),
  today_estimated_cost_usd: z.number(),
});
export type UsageSummary = z.infer<typeof UsageSummarySchema>;

export const GraphNodeSchema = z.object({
  id: z.string(),
  label: z.string(),
  kind: z.string(),
  status: z.string(),
  status_label: z.string(),
  category: z.string(),
  permission: PermissionClassSchema.nullable(),
  capabilities: z.array(z.string()),
  details: z.record(z.string(), z.unknown()),
  active: z.boolean(),
});
export type GraphNode = z.infer<typeof GraphNodeSchema>;
export const GraphSchema = z.object({
  nodes: z.array(GraphNodeSchema),
  edges: z.array(z.object({ id: z.string(), source: z.string(), target: z.string(), kind: z.string(), active: z.boolean() })),
  generated_at: z.string(),
});
export type Graph = z.infer<typeof GraphSchema>;

export const AuditEventSchema = z.object({
  id: z.number(),
  ts: z.string(),
  kind: z.string(),
  level: z.string(),
  task_id: z.string().nullable(),
  tool_id: z.string().nullable(),
  detail: z.unknown(),
});
export type AuditEvent = z.infer<typeof AuditEventSchema>;

export const AppInfoSchema = z.object({
  name: z.string(),
  version: z.string(),
  os: z.string(),
  arch: z.string(),
  data_dir: z.string().nullable(),
  credential_backend: z.string(),
  e2e_build: z.boolean(),
});
export type AppInfo = z.infer<typeof AppInfoSchema>;

export const WorkspaceListingSchema = z.object({
  root: z.string(),
  path: z.string(),
  entries: z.array(
    z.object({
      name: z.string(),
      path: z.string(),
      kind: z.enum(["file", "dir"]),
      bytes: z.number().nullable(),
      modified: z.string().nullable(),
    }),
  ),
});
export type WorkspaceListing = z.infer<typeof WorkspaceListingSchema>;

export const TOPICS = [
  "tasks",
  "approvals",
  "registry",
  "providers",
  "memory",
  "projects",
  "conversations",
  "settings",
  "usage",
  "forge",
  "siblings",
  "missions",
  "notifications",
  "todos",
  "focus",
  "vault",
] as const;
export type Topic = (typeof TOPICS)[number];
export const ChangeEventSchema = z.object({ topic: z.enum(TOPICS), id: z.string().nullable() });

// ---------- pricing ----------
export const PriceEntrySchema = z.object({
  vendor: z.string(),
  model: z.string(),
  input_per_mtok: z.number(),
  output_per_mtok: z.number(),
  verification: z.enum(["verified", "unverified", "user"]),
  source: z.string(),
  as_of: z.string().nullable(),
  availability: z.enum(["current", "deprecated", "unavailable", "unknown"]).optional(),
  availability_note: z.string().nullable().optional(),
});
export type PriceEntry = z.infer<typeof PriceEntrySchema>;
export const PricingScheduleSchema = z.object({ entries: z.array(PriceEntrySchema), seed_conflicts: z.array(z.string()) });

// ---------- Atlas Forge ----------
export const DisciplineSchema = z.enum(["architect", "builder", "debugger", "reconstructor"]);
export type Discipline = z.infer<typeof DisciplineSchema>;
export const ForgeProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  root_path: z.string(),
  test_command: z.string().nullable(),
  build_command: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  exists: z.boolean(),
});
export type ForgeProject = z.infer<typeof ForgeProjectSchema>;
export const ForgeTreeSchema = z.object({
  entries: z.array(z.object({ path: z.string(), kind: z.enum(["file", "dir"]), bytes: z.number().nullable() })),
  truncated: z.boolean(),
});
export const ForgeRunSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  command: z.string(),
  initiated_by: z.enum(["user", "model"]),
  status: z.string(),
  exit_code: z.number().nullable(),
  duration_ms: z.number().nullable(),
  output: z.string(),
  summary: z.object({ framework: z.string(), passed: z.number(), failed: z.number() }).nullable(),
  created_at: z.string(),
  finished_at: z.string().nullable(),
});
export type ForgeRun = z.infer<typeof ForgeRunSchema>;
export const GitStatusSchema = z.object({
  is_repo: z.boolean(),
  branch: z.string().nullable(),
  ahead_behind: z.string().nullable(),
  files: z.array(z.object({ path: z.string(), code: z.string() })),
});
export type GitStatus = z.infer<typeof GitStatusSchema>;
export const GitCommitSchema = z.object({ hash: z.string(), author: z.string(), date: z.string(), subject: z.string() });
export const ForgeChangeSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  path: z.string(),
  kind: z.enum(["create", "modify"]),
  summary: z.string(),
  source: z.string(),
  task_id: z.string().nullable(),
  created_at: z.string(),
  reverted_at: z.string().nullable(),
  revertible: z.boolean(),
  revert_blocker: z.string().nullable(),
});
export type ForgeChange = z.infer<typeof ForgeChangeSchema>;

// ---------- sibling link & mission ledger ----------
export const SiblingSchema = z.object({
  id: z.string(),
  name: z.string(),
  endpoint: z.string(),
  status: z.enum(["paired", "revoked"]),
  remote_version: z.string().nullable(),
  adapter_version: z.string().nullable(),
  capabilities: z
    .object({
      modes: z.array(z.string()).optional(),
      providers: z.array(z.string()).optional(),
      tools: z.array(z.object({ name: z.string(), description: z.string().optional(), dangerous: z.boolean(), available_to_siblings: z.boolean() })).optional(),
      dangerous_tools_policy: z.string().optional(),
    })
    .passthrough()
    .nullable(),
  health: z.object({ status: z.string().optional(), providers: z.array(z.string()).optional(), uptime_s: z.number().optional(), active_missions: z.number().optional() }).passthrough().nullable(),
  last_seen_at: z.string().nullable(),
  last_error: z.string().nullable(),
  paired_at: z.string(),
  revoked_at: z.string().nullable(),
  connected: z.boolean(),
  test_peer: z.boolean(),
});
export type Sibling = z.infer<typeof SiblingSchema>;

export const MissionStateSchema = z.enum(["DRAFT", "PLANNED", "AWAITING_APPROVAL", "RUNNING", "REVIEWING", "COMPLETED", "PAUSED", "FAILED", "CANCELLED", "NEEDS_USER_INPUT"]);
export type MissionState = z.infer<typeof MissionStateSchema>;
export const MissionModeSchema = z.enum(["consultation", "collaborative", "delegated"]);
export type MissionMode = z.infer<typeof MissionModeSchema>;
export const MissionSchema = z.object({
  id: z.string(),
  title: z.string(),
  mode: MissionModeSchema,
  objective: z.string(),
  shared_context: z.string(),
  state: MissionStateSchema,
  sibling_id: z.string().nullable(),
  forge_project_id: z.string().nullable(),
  conversation_id: z.string().nullable(),
  sent_at: z.string().nullable(),
  remote_state: z.string().nullable(),
  remote_seq: z.number(),
  result_summary: z.string().nullable(),
  last_error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Mission = z.infer<typeof MissionSchema>;
export const MissionEventSchema = z.object({
  id: z.number(),
  mission_id: z.string(),
  source: z.enum(["atlas", "prometheus", "user", "system"]),
  kind: z.string(),
  content: z.string(),
  remote_seq: z.number().nullable(),
  created_at: z.string(),
});
export type MissionEvent = z.infer<typeof MissionEventSchema>;
export const MissionDetailSchema = z.object({
  mission: MissionSchema,
  events: z.array(MissionEventSchema),
  outgoing: z.object({ mission_id: z.string(), mode: z.string(), objective: z.string(), context: z.string() }),
  atlas_spend_usd: z.number(),
});
export type MissionDetail = z.infer<typeof MissionDetailSchema>;

// ---------- voice ----------
export const ArtifactKindSchema = z.enum(["tts_engine", "stt_engine", "voice", "stt_model"]);
export const ArtifactStatusSchema = z.object({
  id: z.string(),
  kind: ArtifactKindSchema,
  name: z.string(),
  description: z.string(),
  url: z.string(),
  sha256: z.string(),
  bytes: z.number(),
  platform: z.string().nullable(),
  language: z.string().nullable(),
  license: z.string(),
  license_url: z.string(),
  source: z.string(),
  recommended: z.boolean(),
  note: z.string(),
  state: z.enum(["not_installed", "installed", "damaged"]),
  installing: z.boolean(),
});
export type ArtifactStatus = z.infer<typeof ArtifactStatusSchema>;
export const HardwareSchema = z.object({
  os: z.string(),
  arch: z.string(),
  cpu: z.string(),
  logical_cores: z.number(),
  avx2: z.boolean(),
  total_memory_mb: z.number(),
  available_memory_mb: z.number(),
  free_disk_mb: z.number().nullable(),
  recommended_stt_model: z.string(),
  recommendation: z.string(),
});
export const VoiceStatusSchema = z.object({
  platform: z.string(),
  tts_supported: z.boolean(),
  stt_supported: z.boolean(),
  tts_engine: ArtifactStatusSchema.nullable(),
  stt_engine: ArtifactStatusSchema.nullable(),
  voices: z.array(ArtifactStatusSchema),
  stt_models: z.array(ArtifactStatusSchema),
  selected_voice: z.string(),
  selected_stt_model: z.string(),
  tts_ready: z.boolean(),
  stt_ready: z.boolean(),
  fixtures: z.boolean(),
  hardware: HardwareSchema,
  temp_audio_files: z.number(),
  storage_bytes: z.number(),
});
export type VoiceStatus = z.infer<typeof VoiceStatusSchema>;
export const DownloadProgressSchema = z.discriminatedUnion("phase", [
  z.object({ phase: z.literal("downloading"), received: z.number(), total: z.number().nullable() }),
  z.object({ phase: z.literal("verifying") }),
  z.object({ phase: z.literal("unpacking") }),
  z.object({ phase: z.literal("done") }),
]);
export type DownloadProgress = z.infer<typeof DownloadProgressSchema>;
export const TranscriptSchema = z.object({ text: z.string(), audio_ms: z.number(), elapsed_ms: z.number(), engine: z.string() });
export type Transcript = z.infer<typeof TranscriptSchema>;
export const BenchmarkSchema = z.object({
  fixtures: z.boolean(),
  phrase: z.string(),
  voice: z.string(),
  synthesis_ms: z.number(),
  audio_ms: z.number(),
  synthesis_rtf: z.number(),
  models: z.array(z.object({ id: z.string(), name: z.string(), elapsed_ms: z.number(), real_time_factor: z.number(), transcript: z.string(), word_accuracy: z.number() })),
  hardware: HardwareSchema,
});
export type Benchmark = z.infer<typeof BenchmarkSchema>;

// ---------- desktop presence ----------
export const NotificationSchema = z.object({
  id: z.string(),
  category: z.enum(["approval", "reply", "mission", "error", "reminder", "deadline", "briefing", "focus", "test"]),
  title: z.string(),
  detail: z.string(),
  target: z.string(),
  created_at: z.string(),
  read_at: z.string().nullable(),
  shown_by_system: z.boolean(),
  /** Held by a Focus session: listed, shown when the session ends. */
  held: z.boolean().default(false),
});
export type AtlasNotification = z.infer<typeof NotificationSchema>;
export const NotificationListSchema = z.object({ items: z.array(NotificationSchema), unread: z.number() });
export const DesktopStatusSchema = z.object({
  platform: z.string(),
  tray_supported: z.boolean(),
  tray_visible: z.boolean(),
  shortcut_supported: z.boolean(),
  shortcut_registered: z.string().nullable(),
  shortcut_error: z.string().nullable(),
  notifications_supported: z.boolean(),
  single_instance: z.boolean(),
  notes: z.array(z.string()),
  test_notifications_shown: z.number().nullable(),
});
export type DesktopStatus = z.infer<typeof DesktopStatusSchema>;

// ---------- the owner's tasks (to-dos) ----------
export const TodoSchema = z.object({
  id: z.string(),
  parent_id: z.string().nullable(),
  project_id: z.string().nullable(),
  title: z.string(),
  notes: z.string(),
  status: z.enum(["open", "in_progress", "done", "cancelled"]),
  priority: z.enum(["low", "normal", "high", "urgent"]),
  category: z.string(),
  due_date: z.string().nullable(),
  due_time: z.string().nullable(),
  remind_at: z.string().nullable(),
  recurrence: z.enum(["none", "daily", "weekdays", "weekly", "monthly", "yearly"]),
  recur_interval: z.number(),
  source: z.enum(["user", "atlas"]),
  conversation_id: z.string().nullable(),
  postponed_count: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
  overdue: z.boolean(),
  subtasks_total: z.number(),
  subtasks_done: z.number(),
});
export type Todo = z.infer<typeof TodoSchema>;
export const TodoDetailSchema = z.object({
  task: TodoSchema,
  subtasks: z.array(TodoSchema),
  history: z.array(z.object({ at: z.string(), kind: z.string(), detail: z.string() })),
});
export type TodoDetail = z.infer<typeof TodoDetailSchema>;
export const TodoOverviewSchema = z.object({
  counts: z.object({ open: z.number(), overdue: z.number(), today: z.number(), week: z.number(), done_today: z.number(), done_week: z.number() }),
  categories: z.array(z.string()),
  today: z.string(),
});
export type TodoOverview = z.infer<typeof TodoOverviewSchema>;
export const QuickPreviewSchema = z.object({
  title: z.string(),
  due_date: z.string().nullable(),
  due_time: z.string().nullable(),
  priority: z.string().nullable(),
  category: z.string().nullable(),
  recurrence: z.string().nullable(),
  remind: z.boolean(),
});
export type QuickPreview = z.infer<typeof QuickPreviewSchema>;
export type TodoView = "today" | "week" | "overdue" | "upcoming" | "someday" | "open" | "done" | "all";
export interface TodoFilter {
  view: TodoView;
  project_id?: string | null;
  category?: string | null;
  priority?: string | null;
  search?: string | null;
}
/** A change to a task: `null` clears a value, a missing key leaves it alone. */
export interface TodoPatch {
  title?: string;
  notes?: string;
  priority?: Todo["priority"];
  category?: string;
  project_id?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  remind_at?: string | null;
  recurrence?: Todo["recurrence"];
  status?: Todo["status"];
}

// ---------- scheduler ----------
export const JobSchema = z.object({
  id: z.string(),
  kind: z.string(),
  subject: z.string(),
  run_at: z.string(),
  status: z.enum(["pending", "running", "done", "missed", "cancelled", "failed"]),
  attempts: z.number(),
  result: z.string(),
  created_at: z.string(),
  finished_at: z.string().nullable(),
  label: z.string(),
});
export type Job = z.infer<typeof JobSchema>;
export const ScheduleSchema = z.object({
  paused: z.boolean(),
  summary: z.object({ pending: z.number(), done: z.number(), missed: z.number(), failed: z.number(), next_run_at: z.string().nullable() }),
  jobs: z.array(JobSchema),
});
export type Schedule = z.infer<typeof ScheduleSchema>;

// ---------- Command Center ----------
export const CommandCenterSchema = z.object({
  briefing_text: z.string(),
  briefing: z.object({
    date: z.string(),
    weekday: z.string(),
    overdue: z.array(TodoSchema),
    today: z.array(TodoSchema),
    upcoming: z.array(TodoSchema),
    reminders_today: z.array(z.tuple([z.string(), z.string()])),
    missions: z.array(z.object({ id: z.string(), title: z.string(), state: z.string() })),
    approvals_pending: z.number(),
    recent_conversations: z.array(z.object({ id: z.string(), title: z.string(), updated_at: z.string() })),
    accomplished: z.array(TodoSchema),
    counts: z.object({ open: z.number(), overdue: z.number(), today: z.number(), week: z.number(), done_today: z.number(), done_week: z.number() }),
    notes: z.array(z.string()),
  }),
  schedule: z.object({ pending: z.number(), done: z.number(), missed: z.number(), failed: z.number(), next_run_at: z.string().nullable() }),
  paused: z.boolean(),
  unread_notifications: z.number(),
});
export type CommandCenter = z.infer<typeof CommandCenterSchema>;

// ---------- Focus Mode and the session recap ----------
export const FocusSessionSchema = z.object({
  id: z.string(),
  started_at: z.string(),
  planned_end: z.string(),
  ended_at: z.string().nullable(),
  todo_id: z.string().nullable(),
  todo_title: z.string().nullable(),
  label: z.string(),
  outcome: z.string(),
});
export type FocusSession = z.infer<typeof FocusSessionSchema>;
export const FocusStatusSchema = z.object({
  active: FocusSessionSchema.nullable(),
  history: z.array(FocusSessionSchema),
  min_minutes: z.number(),
  max_minutes: z.number(),
});
export type FocusStatus = z.infer<typeof FocusStatusSchema>;
export const RecapSchema = z.object({
  since: z.string(),
  reminders_delivered: z.number(),
  reminders_missed: z.number(),
  tasks_done: z.array(z.string()),
  notices: z.array(z.tuple([z.string(), z.string()])),
  missions_updated: z.number(),
  interrupted: z.array(z.tuple([z.string(), z.string(), z.string().nullable()])),
  approvals_pending: z.number(),
  empty: z.boolean(),
});
export type Recap = z.infer<typeof RecapSchema>;

// ---------------- Knowledge Vault ----------------

export const VaultSourceSchema = z.object({
  label: z.string(),
  chunk_id: z.string().nullable(),
  document_id: z.string().nullable(),
  title: z.string(),
  kind: z.string(),
  page: z.number().nullable(),
  heading: z.string(),
  excerpt: z.string(),
  sent: z.boolean(),
});
export type VaultSource = z.infer<typeof VaultSourceSchema>;

export const VAULT_STATUSES = ["imported", "processing", "indexed", "needs_reindex", "failed"] as const;
export const VaultDocumentSchema = z.object({
  id: z.string(),
  project_id: z.string().nullable(),
  project_name: z.string().nullable(),
  title: z.string(),
  file_name: z.string(),
  source_path: z.string(),
  kind: z.enum(["txt", "md", "pdf", "docx"]),
  size_bytes: z.number(),
  content_hash: z.string(),
  status: z.enum(VAULT_STATUSES),
  error: z.string().nullable(),
  pages: z.number().nullable(),
  sections: z.number(),
  chunks: z.number(),
  chars: z.number(),
  extractor_version: z.number(),
  index_version: z.number(),
  imported_at: z.string(),
  updated_at: z.string(),
  indexed_at: z.string().nullable(),
  opened_at: z.string().nullable(),
});
export type VaultDocument = z.infer<typeof VaultDocumentSchema>;

export const VaultStatsSchema = z.object({
  documents: z.number(),
  indexed: z.number(),
  processing: z.number(),
  failed: z.number(),
  needs_reindex: z.number(),
  passages: z.number(),
  storage_bytes: z.number(),
});
export const VaultListSchema = z.object({ documents: z.array(VaultDocumentSchema), stats: VaultStatsSchema });

export const VaultCandidateSchema = z.object({
  path: z.string(),
  file_name: z.string(),
  kind: z.string().nullable(),
  size_bytes: z.number(),
  problem: z.string().nullable(),
});
export type VaultCandidate = z.infer<typeof VaultCandidateSchema>;

export const VaultImportResultSchema = z.object({ path: z.string(), document: VaultDocumentSchema.nullable(), error: z.string().nullable() });

export const VaultHitSchema = z.object({
  chunk_id: z.string(),
  document_id: z.string(),
  title: z.string(),
  kind: z.string(),
  project_id: z.string().nullable(),
  page: z.number().nullable(),
  heading: z.string(),
  snippet: z.string(),
  content: z.string(),
  score: z.number(),
  matched_terms: z.number(),
});
export type VaultHit = z.infer<typeof VaultHitSchema>;

export const VaultReaderSchema = z.object({
  document: VaultDocumentSchema,
  parts: z.array(z.object({ chunk_id: z.string(), seq: z.number(), page: z.number().nullable(), heading: z.string(), text: z.string() })),
});
export type VaultReader = z.infer<typeof VaultReaderSchema>;

export type VaultLibrary = { kind: "all" } | { kind: "personal" } | { kind: "project"; project_id: string };
