/**
 * ORBIT's spatial universe for ATLAS: the electric-blue core around Atlas's own voice ring, an atmospheric
 * background, holographic panels, the project journey and four environments.
 *
 * One canvas draws the atmosphere, the layered core (tilted rings, energy mesh, particles, arcs, shield,
 * audio-reactive ring, shockwaves) and pulses along real connections; its animation loop stops while the window
 * is hidden and under reduced motion (a single still frame is drawn). Panels are DOM (accessible, keyboard
 * reachable) and show only real session data. Layout is saved in the session through the core (set_layout).
 */
import { ChevronDown, Maximize2, Minimize2, Plus, Settings2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useReducedMotion } from "@/components/Emblem";
import { api } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { OrbitSession } from "@/lib/schemas";
import { audio } from "@/features/voice/audioEngine";
import {
  ENVIRONMENTS,
  FrameMonitor,
  PANELS,
  budget,
  connections,
  events,
  motion,
  panelContent,
  panelRects,
  readFx,
  readLayout,
  stageEnvironment,
  stages,
  withRect,
  type Content,
  type EnvKey,
  type Fx,
  type Layout,
  type PanelKey,
  type Rect,
} from "./orbitSpace";

const MARK: Record<string, string> = { completed: "✓", done: "✓", running: "▶", failed: "!", awaiting_approval: "?", blocked: "⊘", ready: "○", question: "?", risk: "⚠", file: "▤" };
const TONE: Record<string, string> = { completed: "var(--ok)", done: "var(--ok)", failed: "var(--err)", awaiting_approval: "var(--warn)", risk: "var(--warn)", running: "var(--accent)" };

// ------------------------------------------------------------------ sound (synthesised, optional, quiet)
const CUES: Record<string, [number, number, number, number][]> = {
  enter: [[196, 0, 1.2, 0.5], [293.7, 0.25, 1, 0.35], [392, 0.5, 0.9, 0.25], [587.3, 0.75, 0.7, 0.12]],
  panel: [[523.3, 0, 0.18, 0.25], [784, 0.04, 0.16, 0.12]],
  select: [[659.3, 0, 0.08, 0.18]],
  confirm: [[392, 0, 0.16, 0.3], [587.3, 0.12, 0.24, 0.26]],
  milestone: [[261.6, 0, 1.1, 0.3], [329.6, 0.08, 1, 0.24], [392, 0.16, 0.95, 0.22], [523.3, 0.3, 0.9, 0.16]],
};
let ctx: AudioContext | null = null;
export function playCue(cue: string, volume: number) {
  try {
    ctx = ctx ?? new AudioContext();
    const now = ctx.currentTime;
    for (const [f, start, dur, gain] of CUES[cue] ?? []) {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0, now + start);
      g.gain.linearRampToValueAtTime(gain * 0.25 * volume, now + start + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + start + dur);
      o.connect(g).connect(ctx.destination);
      o.start(now + start);
      o.stop(now + start + dur + 0.05);
    }
  } catch {
    /* sound is decoration: skipped when audio is unavailable */
  }
}

type Props = {
  session: OrbitSession | null;
  coreState: string;
  provisional: { title?: string; brief?: string; ideas?: string[]; phases: string[]; tasks: string[] };
  speaking: boolean;
  onAct: (action: Record<string, unknown>) => Promise<unknown>;
  onLink: (kind: string, ref: string) => void;
  constellation: ReactNode;
  children: ReactNode;
};

type Particle = { a: number; r: number; s: number; size: number; d: number };
type Effect = { kind: "shockwave" | "celebrate" | "pulse"; age: number; life: number; target?: string };

export function OrbitSpace({ session, coreState, provisional, speaking, onAct, onLink, constellation, children }: Props) {
  const reduced = useReducedMotion();
  const [fx, setFx] = useState<Fx>(() => readFx(localStorage.getItem("orbit.fx")));
  const [showFx, setShowFx] = useState(false);
  const [showPanels, setShowPanels] = useState(false);
  const layout = useMemo(() => readLayout(session?.layout), [session?.layout]);
  const [env, setEnv] = useState<EnvKey>(layout.env && ENVIRONMENTS[layout.env] ? layout.env : "command");
  const [local, setLocal] = useState<Layout>(layout);
  const [expanded, setExpanded] = useState<PanelKey | null>(null);
  const [focused, setFocused] = useState<PanelKey | null>(null);
  const [entry, setEntry] = useState<number>(0);
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 900, h: 600 });
  const grants = useAtlasQuery("orbit_grants", api.grants, []);
  const fxRef = useRef<Effect[]>([]);
  const prev = useRef<OrbitSession | null>(null);
  const play = useCallback((cue: string) => fx.sound && !speaking && playCue(cue, fx.volume), [fx.sound, fx.volume, speaking]);

  useEffect(() => setLocal(layout), [layout]);
  useEffect(() => {
    if (session?.id !== prev.current?.id) setEnv(layout.env && ENVIRONMENTS[layout.env] ? layout.env : "command");
  }, [session?.id, layout.env]);
  useEffect(() => localStorage.setItem("orbit.fx", JSON.stringify(fx)), [fx]);

  // the entry sequence: long the first time, short afterwards; skipped under reduced motion or when off
  useEffect(() => {
    if (!fx.cinematic || reduced) return;
    const first = localStorage.getItem("orbit.introSeen") !== "1";
    localStorage.setItem("orbit.introSeen", "1");
    const ms = first ? 2600 : 900;
    setEntry(ms);
    play("enter");
    const t = setTimeout(() => setEntry(0), ms);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // real changes → effects and sounds
  useEffect(() => {
    for (const ev of events(prev.current, session)) {
      if (ev === "project.created" || ev === "plan.updated" || ev === "plan.approved") fxRef.current.push({ kind: "shockwave", age: 0, life: 1.4 });
      if (ev === "project.created" || ev === "workflow.completed") fxRef.current.push({ kind: "celebrate", age: 0, life: 2.2 });
      if (ev === "step.completed") fxRef.current.push({ kind: "pulse", age: 0, life: 1.1, target: "core>operations" });
      play(ev === "project.created" || ev === "workflow.completed" ? "milestone" : ev === "plan.approved" ? "confirm" : "panel");
    }
    prev.current = session;
  }, [session, play]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rects = panelRects(local, env);
  const panelIds = ENVIRONMENTS[env].panels;
  const contents: Record<string, Content> = Object.fromEntries(panelIds.map((p) => [p, panelContent(session, p, grants.data ?? [])]));
  if (!activePlanExists(session) && (provisional.title || provisional.brief || provisional.ideas?.length || provisional.phases.length)) {
    if (contents.brief && provisional.title) contents.brief = { ...contents.brief, items: [{ text: provisional.title, sub: "", state: "title", ref: "" }, ...(provisional.brief ? [{ text: provisional.brief, sub: "Brief", state: "", ref: "" }] : [])], empty: "" };
    if (contents.ideas && provisional.ideas?.length) contents.ideas = { ...contents.ideas, items: provisional.ideas.map((x) => ({ text: x, sub: "idea", state: "", ref: "" })), empty: "" };
    if (contents.plan && provisional.phases.length) contents.plan = { ...contents.plan, items: [...provisional.phases.map((x) => ({ text: x, sub: "phase", state: "", ref: "" })), ...provisional.tasks.map((x) => ({ text: x, sub: "task", state: "", ref: "" }))], empty: "" };
  }
  const px = useCallback(
    (r: Rect) => {
      const narrow = size.w < 820;
      const w = Math.min(Math.max(narrow ? 180 : 200, r.w * size.w), Math.max(180, size.w * (narrow ? 0.31 : 0.34)));
      const h = r.collapsed ? 34 : Math.max(96, r.h * size.h);
      return { x: Math.max(4, Math.min(size.w - w - 4, r.x * size.w)), y: Math.max(4, Math.min(size.h - h - 4, r.y * size.h)), w, h };
    },
    [size],
  );
  const placed = Object.fromEntries(panelIds.map((p) => [p, px(rects[p])])) as Record<PanelKey, { x: number; y: number; w: number; h: number }>;
  const edges = connections(session, env, grants.data ?? []).filter((e) => !rects[e.to]?.hidden && (e.from === "core" || !rects[e.from]?.hidden));

  // persist layout (debounced) through the core
  const saveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const persist = useCallback(
    (next: Layout) => {
      setLocal(next);
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => void onAct({ action: "set_layout", layout: next }), 500);
    },
    [onAct],
  );
  const changeEnv = (e: EnvKey) => {
    setEnv(e);
    setExpanded(null);
    persist({ ...local, env: e });
    play("select");
  };

  // ---------------- the canvas loop (atmosphere, core, pulses) ----------------
  const stateRef = useRef({ coreState, edges, placed, size, fx, reduced });
  stateRef.current = { coreState, edges, placed, size, fx, reduced };
  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const g = cv.getContext("2d");
    if (!g) return;
    const monitor = new FrameMonitor();
    let particles: Particle[] = [];
    let t = 0;
    let last = performance.now();
    let raf = 0;
    let bg: HTMLCanvasElement | null = null;
    let bgKey = "";
    const spawn = (n: number) => Array.from({ length: n }, (_, i) => ({ a: (i * 2.399) % (Math.PI * 2), r: 1.1 + ((i * 0.37) % 2.1), s: 0.4 + ((i * 0.13) % 0.8), size: 0.6 + ((i * 0.29) % 1.6), d: 0.3 + ((i * 0.17) % 0.7) }));
    const frame = (now: number) => {
      const st = stateRef.current;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const { w, h } = st.size;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
      }
      const t0 = performance.now();
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      t += st.reduced ? 0 : dt;
      const b = budget(st.fx, st.reduced, monitor.quality);
      if (particles.length !== b.particles) particles = spawn(b.particles);
      const m = motion(st.coreState);
      const [r0, g0, b0] = m.tone;
      const col = (a: number) => `rgba(${r0},${g0},${b0},${Math.max(0, Math.min(1, a))})`;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      // atmosphere: cached deep-navy gradient, hex grid and distant points; gentle parallax
      const key = `${w}x${h}${st.fx.depth}`;
      if (bgKey !== key) {
        bg = document.createElement("canvas");
        bg.width = w + 40;
        bg.height = h + 40;
        const q = bg.getContext("2d")!;
        const rg = q.createRadialGradient(bg.width / 2, bg.height / 2, 0, bg.width / 2, bg.height / 2, Math.max(w, h) * 0.7);
        rg.addColorStop(0, "#0b1a33");
        rg.addColorStop(0.5, "#07101f");
        rg.addColorStop(1, "#04070e");
        q.fillStyle = rg;
        q.fillRect(0, 0, bg.width, bg.height);
        q.strokeStyle = "rgba(60,207,230,0.05)";
        q.lineWidth = 0.8;
        const sz = 34;
        const dx = sz * 1.5;
        const dy = sz * Math.sqrt(3);
        for (let c = 0; c < bg.width / dx + 2; c++)
          for (let r = 0; r < bg.height / dy + 2; r++) {
            const cx = c * dx;
            const cy = r * dy + (c % 2 ? dy / 2 : 0);
            q.beginPath();
            for (let k = 0; k <= 6; k++) q.lineTo(cx + sz * Math.cos((Math.PI / 3) * k), cy + sz * Math.sin((Math.PI / 3) * k));
            q.stroke();
          }
        for (let i = 0; i < (bg.width * bg.height) / 9000; i++) {
          q.fillStyle = `rgba(200,235,255,${0.05 + ((i * 7) % 30) / 100})`;
          q.beginPath();
          q.arc((i * 97.3) % bg.width, (i * 53.7) % bg.height, 0.4 + ((i * 3) % 9) / 10, 0, Math.PI * 2);
          q.fill();
        }
        bgKey = key;
      }
      const amp = { off: 0, gentle: 0.24, dynamic: 0.6 }[st.fx.camera] * (st.reduced ? 0 : 1);
      if (bg) g.drawImage(bg, -20 + Math.sin(t * 0.07) * 20 * amp, -20 + Math.cos(t * 0.05) * 20 * amp);
      if (st.fx.depth === "immersive") {
        g.strokeStyle = "rgba(90,170,255,0.05)";
        g.lineWidth = 1.2;
        for (let k = 0; k < 3; k++) {
          g.beginPath();
          for (let x = 0; x <= w + 40; x += 40) g.lineTo(x, h * (0.25 + 0.25 * k) + Math.sin(x / 180 + t * 0.12 * (k + 1) + k) * 26);
          g.stroke();
        }
      }
      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) * 0.075;
      // real connections and the pulses travelling along them
      const effects = fxRef.current;
      for (const e of st.edges) {
        const pb = st.placed[e.to];
        if (!pb) continue;
        const bxp = { x: Math.min(Math.max(cx, pb.x), pb.x + pb.w), y: Math.min(Math.max(cy, pb.y), pb.y + pb.h) };
        let a: { x: number; y: number };
        if (e.from !== "core") {
          const pa = st.placed[e.from];
          if (!pa) continue;
          a = { x: pa.x + pa.w / 2, y: pa.y + pa.h / 2 };
        } else {
          const d = Math.hypot(bxp.x - cx, bxp.y - cy) || 1;
          a = { x: cx + ((bxp.x - cx) / d) * R * 1.4, y: cy + ((bxp.y - cy) / d) * R * 1.4 };
        }
        const lg = g.createLinearGradient(a.x, a.y, bxp.x, bxp.y);
        lg.addColorStop(0, "rgba(60,207,230,0.45)");
        lg.addColorStop(1, "rgba(60,207,230,0.12)");
        g.strokeStyle = lg;
        g.lineWidth = 1.1;
        g.beginPath();
        g.moveTo(a.x, a.y);
        g.lineTo(bxp.x, bxp.y);
        g.stroke();
        if (e.kind !== "context") {
          g.fillStyle = "rgba(160,200,230,0.6)";
          g.font = "10px Inter, sans-serif";
          g.fillText(e.kind, (a.x + bxp.x) / 2 + 4, (a.y + bxp.y) / 2 - 4);
        }
        const keyId = `${e.from}>${e.to}`;
        const boost = effects.some((f) => f.kind === "pulse" && f.target === keyId);
        const ph = (t * 0.35 + (keyId.length % 10) / 10) % 1;
        g.fillStyle = col(boost ? 0.95 : 0.5);
        g.beginPath();
        g.arc(a.x + (bxp.x - a.x) * ph, a.y + (bxp.y - a.y) * ph, boost ? 3.4 : 2, 0, Math.PI * 2);
        g.fill();
      }
      // the core: shield, mesh, rings, particles, audio ring, pulse, arcs, effects
      const sh = m.shield * (0.6 + 0.4 * b.scale);
      const sg = g.createRadialGradient(cx, cy, R * 1.7, cx, cy, R * 3.1);
      sg.addColorStop(0, col(0));
      sg.addColorStop(0.7, col(sh * 0.55));
      sg.addColorStop(1, col(0));
      g.fillStyle = sg;
      g.beginPath();
      g.arc(cx, cy, R * 3.1, 0, Math.PI * 2);
      g.fill();
      g.strokeStyle = col(0.1 + 0.12 * m.glow * b.scale);
      g.lineWidth = 0.8;
      const mesh = 8;
      for (let k = 0; k < mesh; k++) {
        const a1 = t * 0.12 + (k * Math.PI * 2) / mesh;
        const a2 = t * 0.12 + (((k + 2) % mesh) * Math.PI * 2) / mesh;
        g.beginPath();
        g.moveTo(cx + Math.cos(a1) * R * 1.22, cy + Math.sin(a1) * R * 1.22);
        g.lineTo(cx + Math.cos(a2) * R * 1.22, cy + Math.sin(a2) * R * 1.22);
        g.stroke();
      }
      for (let i = 0; i < b.rings; i++) {
        const rr = R * (1.45 + 0.34 * i);
        const dir = i % 2 ? -1 : 1;
        const orient = ((t * m.ringSpeed * 6 * dir * (1 - 0.12 * i) + i * 37) * Math.PI) / 180;
        const incline = 18 + m.tilt * ((i % 3) - 1) * 0.6 + 50;
        const ratio = Math.max(0.18, Math.cos((incline * Math.PI) / 180));
        const alpha = (0.18 + 0.32 * m.glow) * (1 - 0.13 * i) * (0.55 + 0.45 * b.scale);
        g.save();
        g.translate(cx, cy);
        g.rotate(orient);
        g.strokeStyle = col(alpha);
        g.lineWidth = i ? 1.1 : 1.5;
        if ((st.coreState === "approval" || st.coreState === "paused") && i === 0) g.setLineDash([6, 6]);
        g.beginPath();
        g.ellipse(0, 0, rr, rr * ratio, 0, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
        const ba = t * (0.6 + 0.25 * i) * dir * Math.max(0.2, m.ringSpeed / 2) + i;
        g.fillStyle = col(Math.min(1, alpha * 2.4));
        g.beginPath();
        g.arc(Math.cos(ba) * rr, Math.sin(ba) * rr * ratio, 2.6, 0, Math.PI * 2);
        g.fill();
        g.restore();
      }
      for (const p of particles) {
        p.a = (p.a + dt * m.flow * b.scale * p.s * 0.6) % (Math.PI * 2);
        p.r += -m.inflow * dt * 0.35 * p.s * (st.reduced ? 0 : 1);
        if (p.r < 1.05) p.r = 3.2;
        else if (p.r > 3.3) p.r = 1.1;
        g.fillStyle = col((0.15 + 0.55 * p.d) * (0.4 + 0.6 * m.glow));
        g.beginPath();
        g.arc(cx + Math.cos(p.a) * p.r * R, cy + Math.sin(p.a) * p.r * R * 0.62, p.size * 0.7, 0, Math.PI * 2);
        g.fill();
      }
      const level = st.coreState === "listening" || st.coreState === "speaking" ? audio.level() : 0;
      if (level > 0.01) {
        g.strokeStyle = col(0.4 + 0.5 * level);
        g.lineWidth = 1.6;
        g.beginPath();
        for (let k = 0; k <= 72; k++) {
          const an = (k * Math.PI * 2) / 72;
          const rr = R * 1.18 + Math.sin(an * 6 + t * (st.coreState === "speaking" ? 8 : 5)) * level * R * 0.22;
          g.lineTo(cx + Math.cos(an) * rr, cy + Math.sin(an) * rr);
        }
        g.stroke();
      }
      if (m.pulse > 0 && !st.reduced) {
        const ph = (t * m.pulse) % 1;
        g.strokeStyle = col((1 - ph) * 0.35 * b.scale);
        g.lineWidth = 1.2;
        g.beginPath();
        g.arc(cx, cy, R * (1.05 + 0.6 * ph), 0, Math.PI * 2);
        g.stroke();
      }
      if (st.fx.energy && !st.reduced && Math.random() < m.arcs * dt * b.scale * 2) {
        const an = Math.random() * Math.PI * 2;
        g.strokeStyle = "rgba(200,245,255,0.8)";
        g.lineWidth = 1.1;
        g.beginPath();
        for (let k = 0; k < 6; k++) {
          const rr = R * (1.02 + 0.12 * k);
          const j = an + (Math.random() - 0.5) * 0.18;
          g.lineTo(cx + Math.cos(j) * rr, cy + Math.sin(j) * rr);
        }
        g.stroke();
      }
      for (const e of effects) {
        e.age += dt;
        const k = Math.min(1, e.age / e.life);
        if (!st.fx.energy) continue;
        if (e.kind === "shockwave") {
          g.strokeStyle = col((1 - k) * 0.55);
          g.lineWidth = 2 * (1 - k) + 0.5;
          g.beginPath();
          g.ellipse(cx, cy, R * 1.1 + k * Math.max(w, h) * 0.45, (R * 1.1 + k * Math.max(w, h) * 0.45) * 0.92, 0, 0, Math.PI * 2);
          g.stroke();
        } else if (e.kind === "celebrate") {
          for (let j = 0; j < 28; j++) {
            const an = (j * Math.PI * 2) / 28 + j * 0.3;
            const rr = R * (1.2 + 3.2 * k);
            g.fillStyle = `rgba(170,240,255,${(1 - k) * 0.9})`;
            g.beginPath();
            g.arc(cx + Math.cos(an) * rr, cy + Math.sin(an) * rr * 0.8, 2.4 * (1 - k) + 0.6, 0, Math.PI * 2);
            g.fill();
          }
        }
      }
      fxRef.current = effects.filter((e) => e.age < e.life);
      monitor.add((performance.now() - t0) * 2);
      if (!st.reduced && !document.hidden) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    const vis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(frame);
    };
    document.addEventListener("visibilitychange", vis);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", vis);
    };
  }, [reduced]);

  // ---------------- panels: drag, resize, collapse, expand, hide ----------------
  const drag = useRef<{ pid: PanelKey; mode: "move" | "size"; x: number; y: number; r: { x: number; y: number; w: number; h: number } } | null>(null);
  const onDown = (pid: PanelKey, mode: "move" | "size") => (e: React.PointerEvent) => {
    if (expanded) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { pid, mode, x: e.clientX, y: e.clientY, r: placed[pid] };
    setFocused(pid);
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    const r = d.mode === "move" ? { ...d.r, x: d.r.x + dx, y: d.r.y + dy } : { ...d.r, w: Math.max(180, d.r.w + dx), h: Math.max(96, d.r.h + dy) };
    setLocal((l) => withRect(l, env, d.pid, { x: r.x / size.w, y: r.y / size.h, w: r.w / size.w, h: r.h / size.h }));
  };
  const onUp = () => {
    if (!drag.current) return;
    drag.current = null;
    persist(local);
  };
  const setPanel = (pid: PanelKey, change: Partial<Rect>) => persist(withRect(local, env, pid, change));
  const goStage = (key: (typeof stages extends (...a: never[]) => infer R ? R : never)[number]["key"]) => {
    const [e, pid] = stageEnvironment(key);
    if (e !== env) changeEnv(e);
    setFocused(pid);
    if (rects[pid]?.hidden) setPanel(pid, { hidden: false });
  };
  const hidden = panelIds.filter((p) => rects[p].hidden);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {(Object.keys(ENVIRONMENTS) as EnvKey[]).map((k) => (
          <button
            key={k}
            onClick={() => changeEnv(k)}
            title={ENVIRONMENTS[k].purpose}
            aria-pressed={env === k}
            className={cn("rounded-md border px-2.5 py-1 text-[0.7rem] font-semibold tracking-[0.12em]", env === k ? "border-accent bg-accent text-text-inverse" : "border-line-2 text-text-2 hover:text-text-1")}
          >
            {ENVIRONMENTS[k].name.toUpperCase()}
          </button>
        ))}
        <div className="relative ml-auto flex gap-1.5">
          <button className="rounded-md border border-line-2 px-2 py-1 text-xs text-text-2 hover:text-text-1" onClick={() => setShowPanels((v) => !v)} aria-expanded={showPanels}>
            Panels <ChevronDown className="inline size-3" />
          </button>
          <button className="rounded-md border border-line-2 px-2 py-1 text-xs text-text-2 hover:text-text-1" onClick={() => setShowFx((v) => !v)} aria-expanded={showFx} aria-label="ORBIT visual experience">
            <Settings2 className="inline size-3.5" /> Visual
          </button>
          {showPanels && (
            <div className="absolute right-20 top-8 z-50 w-60 rounded-md border border-line-2 bg-bg-2 p-2 text-sm shadow-xl">
              {hidden.length ? hidden.map((p) => <button key={p} className="block w-full rounded px-2 py-1 text-left hover:bg-bg-3" onClick={() => (setPanel(p, { hidden: false }), setShowPanels(false))}>Show {PANELS[p][0]}</button>) : <div className="px-2 py-1 text-text-3">All panels of this environment are shown</div>}
              <button className="mt-1 block w-full rounded px-2 py-1 text-left hover:bg-bg-3" onClick={() => (persist({ ...local, panels: { ...local.panels, [env]: {} } }), setShowPanels(false))}>Reset this environment's layout</button>
            </div>
          )}
          {showFx && <FxPanel fx={fx} setFx={setFx} reduced={reduced} onClose={() => setShowFx(false)} />}
        </div>
      </div>
      <nav aria-label="Project stages" className="flex flex-wrap items-center gap-1 text-[0.68rem] tracking-[0.1em]">
        {stages(session).map((st, i) => (
          <span key={st.key} className="flex items-center gap-1">
            {i > 0 && <span className="text-text-3">→</span>}
            <button onClick={() => goStage(st.key)} title={`${st.name}: ${st.state} — ${st.why}`} aria-label={`Stage ${st.name}, ${st.state}: ${st.why}`} className={cn("px-1 py-0.5 font-semibold", st.state === "done" ? "text-ok" : st.state === "current" ? "text-accent-strong" : "text-text-3")}>
              {st.state === "done" ? "✓" : st.state === "current" ? "●" : "○"} {st.name.toUpperCase()}
            </button>
          </span>
        ))}
      </nav>
      <div ref={box} className="relative min-h-0 flex-1 overflow-hidden rounded-lg border border-line-1" onPointerMove={onMove} onPointerUp={onUp}>
        <canvas ref={canvas} className="absolute inset-0 h-full w-full" aria-hidden />
        {ENVIRONMENTS[env].constellation && <div className="absolute inset-0">{constellation}</div>}
        <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">{children}</div>
        {panelIds.map((pid, i) => {
          const r = rects[pid];
          if (r.hidden) return null;
          const p = placed[pid];
          const isExp = expanded === pid;
          const c = contents[pid]!;
          const provisionalPanel = !activePlanExists(session) && c.items.length > 0 && ["brief", "ideas", "plan"].includes(pid);
          return (
            <section
              key={`${env}-${pid}`}
              role="region"
              aria-label={`${PANELS[pid][0]} panel`}
              onPointerDown={() => setFocused(pid)}
              style={isExp ? { left: "12%", top: "8%", width: "76%", height: "84%", zIndex: 40, transformOrigin: "center" } : { left: p.x, top: p.y, width: p.w, height: p.h, zIndex: focused === pid ? 30 : 20, animationDelay: `${i * 70}ms`, transformOrigin: `${size.w / 2 - p.x}px ${size.h / 2 - p.y}px` }}
              className={cn(
                "absolute flex flex-col rounded-[10px] border bg-[linear-gradient(180deg,rgba(10,26,48,0.94),rgba(5,12,24,0.92))] shadow-[0_8px_30px_rgba(0,0,0,0.45)] backdrop-blur-sm transition-[border-color,opacity] duration-200",
                focused === pid || isExp ? "border-[rgba(60,207,230,0.8)]" : "border-[rgba(60,207,230,0.28)]",
                expanded && !isExp && "opacity-35",
                !reduced && entry === 0 && "orbit-materialise",
              )}
            >
              <header className="flex cursor-grab items-center gap-1 px-2.5 py-1.5 active:cursor-grabbing" onPointerDown={onDown(pid, "move")} onDoubleClick={() => setExpanded(isExp ? null : pid)}>
                <h3 className="text-[0.66rem] font-semibold tracking-[0.12em] text-accent-strong">{PANELS[pid][0].toUpperCase()}</h3>
                <span className="text-[0.62rem] text-text-3">{c.items.length || ""}</span>
                <span className="ml-auto flex items-center" onPointerDown={(e) => e.stopPropagation()}>
                  {pid === "files" && (
                    <button aria-label="Share a file with Atlas" title="Share a file with Atlas" className="px-1 text-accent-strong" onClick={() => void api.shareFile().then(() => grants.reload()).catch(() => {})}>
                      <Plus className="size-3.5" />
                    </button>
                  )}
                  <button aria-label={`Collapse or open ${PANELS[pid][0]}`} className="px-1 text-text-3 hover:text-text-1" onClick={() => setPanel(pid, { collapsed: !r.collapsed })}>
                    <ChevronDown className={cn("size-3.5 transition-transform", r.collapsed && "-rotate-90")} />
                  </button>
                  <button aria-label={`Expand or restore ${PANELS[pid][0]}`} className="px-1 text-text-3 hover:text-text-1" onClick={() => setExpanded(isExp ? null : pid)}>
                    {isExp ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
                  </button>
                  <button aria-label={`Hide ${PANELS[pid][0]} (its data stays)`} className="px-1 text-text-3 hover:text-text-1" onClick={() => setPanel(pid, { hidden: true })}>
                    <X className="size-3.5" />
                  </button>
                </span>
              </header>
              {!r.collapsed && (
                <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2 text-[0.8rem]">
                  {provisionalPanel && <p className="mb-1 text-[0.65rem] text-text-3">arriving…</p>}
                  {!c.items.length && <p className="text-text-3">{c.empty}</p>}
                  {c.items.map((it, k) => {
                    const kind = pid === "files" ? "file" : it.state === "awaiting_approval" ? "approve" : "task";
                    const body = (
                      <>
                        <span style={{ color: TONE[it.state] ?? "var(--accent)" }}>{MARK[it.state] ?? "•"}</span> <span className={cn(it.state === "title" && "text-[0.95rem] font-semibold")}>{it.text}</span>
                        {it.sub && <span className="block text-[0.68rem] text-text-3">{it.sub}</span>}
                      </>
                    );
                    return it.ref ? (
                      <button key={k} className="mb-1.5 block w-full text-left hover:text-accent-strong" onClick={() => onLink(kind, it.ref)}>
                        {body}
                      </button>
                    ) : (
                      <div key={k} className="mb-1.5">
                        {body}
                      </div>
                    );
                  })}
                </div>
              )}
              {!r.collapsed && !isExp && <div className="absolute bottom-0.5 right-0.5 size-3 cursor-se-resize border-b border-r border-[rgba(60,207,230,0.5)]" onPointerDown={onDown(pid, "size")} aria-hidden />}
            </section>
          );
        })}
        {entry > 0 && <EntryOverlay ms={entry} onSkip={() => setEntry(0)} />}
      </div>
    </div>
  );
}

function activePlanExists(s: OrbitSession | null) {
  return !!s && s.active_version > 0;
}

function EntryOverlay({ ms, onSkip }: { ms: number; onSkip: () => void }) {
  useEffect(() => {
    const k = () => onSkip();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onSkip]);
  return (
    <div className="orbit-entry absolute inset-0 z-50 grid cursor-pointer place-items-center" style={{ animationDuration: `${ms}ms` }} onClick={onSkip} role="presentation" aria-label="Entering ORBIT (click or press a key to skip)">
      <svg viewBox="-100 -100 200 200" className="size-[60%]" aria-hidden>
        <defs>
          <radialGradient id="orbit-core">
            <stop offset="0" stopColor="#e6fbff" />
            <stop offset="0.3" stopColor="#3ccfe6" />
            <stop offset="1" stopColor="#3ccfe6" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle r="30" fill="url(#orbit-core)" className="orbit-entry-core" style={{ animationDuration: `${ms}ms` }} />
        {[38, 52, 66, 80].map((r, i) => (
          <ellipse key={r} rx={r} ry={r * 0.42} fill="none" stroke="#7df3ff" strokeOpacity="0.7" strokeWidth="0.8" transform={`rotate(${i * 47})`} pathLength={1} className="orbit-entry-ring" style={{ animationDuration: `${ms}ms`, animationDelay: `${(ms * (0.15 + i * 0.07)) | 0}ms` }} />
        ))}
      </svg>
      <p className="absolute bottom-6 text-xs tracking-[0.2em] text-[#7df3ff]/70">ORBIT · click or press any key to skip</p>
    </div>
  );
}

function FxPanel({ fx, setFx, reduced, onClose }: { fx: Fx; setFx: (f: Fx) => void; reduced: boolean; onClose: () => void }) {
  const row = (label: string, key: "intensity" | "particles" | "depth" | "camera", opts: string[]) => (
    <label className="flex items-center justify-between gap-2 py-1">
      <span>{label}</span>
      <select className="rounded border border-line-2 bg-bg-3 px-1 py-0.5" value={fx[key]} onChange={(e) => setFx({ ...fx, [key]: e.target.value } as Fx)}>
        {opts.map((o) => (
          <option key={o} value={o}>
            {o[0]!.toUpperCase() + o.slice(1)}
          </option>
        ))}
      </select>
    </label>
  );
  const check = (label: string, key: "cinematic" | "energy" | "sound") => (
    <label className="flex items-center gap-2 py-1">
      <input type="checkbox" checked={fx[key]} onChange={(e) => setFx({ ...fx, [key]: e.target.checked })} /> {label}
    </label>
  );
  return (
    <div className="absolute right-0 top-8 z-50 w-72 rounded-md border border-line-2 bg-bg-2 p-3 text-sm shadow-xl" role="dialog" aria-label="ORBIT visual experience">
      {row("Animation intensity", "intensity", ["subtle", "balanced", "spectacular"])}
      {row("Particle density", "particles", ["low", "medium", "high"])}
      {row("Environment depth", "depth", ["standard", "immersive"])}
      {row("Camera movement", "camera", ["off", "gentle", "dynamic"])}
      {check("Cinematic entry", "cinematic")}
      {check("Energy effects (arcs, shockwaves, pulses)", "energy")}
      {check("ORBIT sounds (quiet, synthesised; never over speech)", "sound")}
      <label className="flex items-center justify-between gap-2 py-1">
        <span>Sound volume</span>
        <input type="range" min={0} max={100} value={Math.round(fx.volume * 100)} onChange={(e) => setFx({ ...fx, volume: Number(e.target.value) / 100 })} aria-label="ORBIT sound volume" />
      </label>
      <p className="mt-1 text-xs text-text-3">{reduced ? "Reduced motion is on: the scene is drawn still and panels appear without animation." : "Reduced motion (Settings) turns all motion off."}</p>
      <button className="mt-2 rounded border border-line-2 px-2 py-1 text-xs" onClick={onClose}>
        Close
      </button>
    </div>
  );
}
