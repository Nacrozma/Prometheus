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
  permissions: z.object({ local_write: gate, network_tools: gate }),
  memory: z.object({ enabled: z.boolean(), max_retrieved: z.number() }),
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
  voice: z.object({ enabled: z.boolean(), speak_responses: z.boolean(), language: z.string() }),
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
