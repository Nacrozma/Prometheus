import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "@/components/Emblem";
import { cn } from "@/lib/format";
import type { VoicePhase } from "@/state/voice";
import { audio } from "./audioEngine";
import { BANDS, RING_FRAGMENT, RING_VERTEX, STATE_INDEX, computeBands } from "./ringShader";

const LABEL: Record<VoicePhase, string> = {
  idle: "Atlas is ready",
  listening: "Listening",
  transcribing: "Understanding what you said",
  processing: "Thinking",
  speaking: "Speaking",
  paused: "Paused",
  interrupted: "Stopped",
  error: "Voice problem",
  offline: "Voice is off",
};

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
  const s = gl.createShader(type);
  if (!s) return null;
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    console.warn("[atlas] voice ring shader:", gl.getShaderInfoLog(s));
    return null;
  }
  return s;
}

/**
 * The electric-blue voice ring. It moves only with real audio: the analyser of whatever Atlas is
 * playing (speaking) or recording (listening). Idle is a slow breathing glow; reduced motion shows
 * a still ring; without WebGL2 a static ring stands in. Rendering pauses while the window is hidden.
 */
export function VoiceRing({ phase, size = 72, className }: { phase: VoicePhase; size?: number; className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const [fallback, setFallback] = useState(false);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const redraw = useRef<(() => void) | null>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let gl: WebGL2RenderingContext | null = null;
    try {
      gl = el.getContext("webgl2", { premultipliedAlpha: true, antialias: true });
    } catch {
      gl = null;
    }
    if (!gl) {
      setFallback(true);
      return;
    }
    const vs = compile(gl, gl.VERTEX_SHADER, RING_VERTEX);
    const fs = compile(gl, gl.FRAGMENT_SHADER, RING_FRAGMENT);
    const prog = gl.createProgram();
    if (!vs || !fs || !prog) return setFallback(true);
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return setFallback(true);
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    const u = {
      res: gl.getUniformLocation(prog, "u_res"),
      time: gl.getUniformLocation(prog, "u_time"),
      level: gl.getUniformLocation(prog, "u_level"),
      fade: gl.getUniformLocation(prog, "u_fade"),
      state: gl.getUniformLocation(prog, "u_state"),
      bands: gl.getUniformLocation(prog, "u_bands"),
    };
    gl.uniform1i(u.bands, 0);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    const bands = new Float32Array(BANDS);
    const bytes = new Uint8Array(BANDS);
    let freq = new Uint8Array(256);
    let level = 0;
    let frames = 0;
    let raf = 0;
    let last = 0;
    let lastAttr = 0;
    const started = performance.now();

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const px = Math.round(el.clientWidth * dpr);
      if (el.width !== px) {
        el.width = px;
        el.height = px;
      }
    };

    const draw = (now: number, animate: boolean) => {
      resize();
      const ph = phaseRef.current;
      const analyser = audio.analyser();
      if (analyser && (ph === "speaking" || ph === "listening" || ph === "paused")) {
        if (freq.length !== analyser.frequencyBinCount) freq = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(freq);
        computeBands(freq, bands);
        const l = audio.level();
        level += (l - level) * (l > level ? 0.5 : 0.12);
      } else {
        for (let i = 0; i < BANDS; i++) bands[i] = (bands[i] ?? 0) * 0.85;
        level *= 0.85;
      }
      for (let i = 0; i < BANDS; i++) bytes[i] = Math.min(255, Math.round((bands[i] ?? 0) * 255));
      gl!.bindTexture(gl!.TEXTURE_2D, tex);
      gl!.texImage2D(gl!.TEXTURE_2D, 0, gl!.R8, BANDS, 1, 0, gl!.RED, gl!.UNSIGNED_BYTE, bytes);
      gl!.viewport(0, 0, el.width, el.height);
      gl!.clearColor(0, 0, 0, 0);
      gl!.clear(gl!.COLOR_BUFFER_BIT);
      gl!.uniform2f(u.res, el.width, el.height);
      gl!.uniform1f(u.time, animate ? (now - started) / 1000 : 0);
      gl!.uniform1f(u.level, Math.min(1, level * 3));
      gl!.uniform1f(u.fade, ph === "interrupted" ? Math.max(0, 1 - (now - audio.interruptedAt) / 700) : 0);
      gl!.uniform1i(u.state, STATE_INDEX[ph]);
      gl!.drawArrays(gl!.TRIANGLE_STRIP, 0, 4);
      frames++;
      // Expose what the ring measured (for tests and diagnostics), a few times a second.
      // Still frames (reduced motion) are rare, so they report at once.
      if ((!animate || now - lastAttr > 200) && root.current) {
        lastAttr = now;
        root.current.dataset.level = level.toFixed(3);
        root.current.dataset.frames = String(frames);
      }
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const ph = phaseRef.current;
      // Quiet states render at a gentle rate to save power.
      const minGap = ph === "idle" || ph === "offline" || ph === "paused" ? 1000 / 20 : 0;
      if (now - last < minGap) return;
      last = now;
      draw(now, true);
    };
    const start = () => {
      cancelAnimationFrame(raf);
      if (document.hidden) return;
      if (reduced) draw(performance.now(), false);
      else raf = requestAnimationFrame(loop);
    };
    const onVisibility = () => (document.hidden ? cancelAnimationFrame(raf) : start());
    redraw.current = () => draw(performance.now(), false);
    start();
    document.addEventListener("visibilitychange", onVisibility);
    // Reduced motion: still redraw when the state changes.
    const unsub = reduced ? audio.subscribe(() => requestAnimationFrame((t) => draw(t, false))) : () => {};
    return () => {
      cancelAnimationFrame(raf);
      unsub();
      redraw.current = null;
      document.removeEventListener("visibilitychange", onVisibility);
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [reduced]);

  // Reduced motion: no animation loop, so draw once whenever the state changes.
  useEffect(() => {
    if (reduced) redraw.current?.();
  }, [phase, reduced]);

  return (
    <div
      ref={root}
      role="img"
      aria-label={LABEL[phase]}
      data-voice-ring
      data-state={phase}
      data-renderer={fallback ? "static" : "webgl2"}
      data-reduced={String(reduced)}
      data-level="0"
      className={cn("relative shrink-0", className)}
      style={{ width: size, height: size }}
    >
      {fallback ? (
        <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden>
          <circle
            cx="50"
            cy="50"
            r="30"
            fill="none"
            strokeWidth={phase === "speaking" ? 3.5 : 2.5}
            stroke={phase === "error" ? "#f59e0b" : phase === "offline" ? "#475569" : "#3ccfe6"}
            opacity={phase === "offline" ? 0.5 : phase === "idle" ? 0.7 : 1}
            style={{ filter: phase === "offline" ? undefined : "drop-shadow(0 0 6px rgb(60 207 230 / 0.6))" }}
          />
        </svg>
      ) : (
        <canvas ref={canvas} className="h-full w-full" aria-hidden />
      )}
    </div>
  );
}
