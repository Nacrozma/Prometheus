import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/format";
import { ease, FRAGMENT_SHADER, OFFLINE_ENERGY, STATE_ENERGY, stateIndex, VERTEX_SHADER, type Easing, type SolarState } from "./solarShader";

/** Respect the OS setting and Atlas's own Appearance → Motion choice. */
function prefersReducedMotion(): boolean {
  const root = document.documentElement.dataset.motion;
  if (root === "reduced") return true;
  if (root === "full") return false;
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type);
  if (!sh) throw new Error("createShader failed");
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh) ?? "";
    gl.deleteShader(sh);
    throw new Error(`shader compile: ${log}`);
  }
  return sh;
}

const LABEL: Record<SolarState, string> = {
  idle: "idle",
  thinking: "thinking",
  speaking: "responding",
  adapting: "adapting",
  offline: "not connected",
};

export interface PrometheusAvatarProps {
  state: SolarState;
  /**
   * 0..1 signal that drives the corona while speaking (the original used microphone level).
   * Atlas passes the real rate of incoming sibling messages; with no signal it stays 0.
   */
  activity?: number;
  size?: number;
  className?: string;
  /** Play the short "star birth" scale-in on mount (skipped under reduced motion). */
  birth?: boolean;
}

/**
 * Prometheus's solar avatar, scoped to its own canvas and WebGL2 context. It never replaces Atlas's
 * emblem. Rendering pauses while the canvas is off-screen or the window is hidden; reduced motion
 * draws a single still frame per state change; without WebGL2 a static CSS rendering is shown.
 */
export function PrometheusAvatar({ state, activity = 0, size = 160, className, birth = true }: PrometheusAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [fallback, setFallback] = useState(false);
  const live = useRef({ state, activity });
  live.current = { state, activity };
  const redraw = useRef<(() => void) | null>(null);

  useEffect(() => {
    redraw.current?.();
  }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let gl: WebGL2RenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl2", { antialias: false, alpha: false, depth: false, stencil: false, powerPreference: "low-power", preserveDrawingBuffer: false });
    } catch {
      gl = null;
    }
    if (!gl) {
      setFallback(true);
      return;
    }
    let program: WebGLProgram | null = null;
    let vbo: WebGLBuffer | null = null;
    let vao: WebGLVertexArrayObject | null = null;
    try {
      const vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
      const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
      program = gl.createProgram();
      if (!program) throw new Error("createProgram failed");
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(`link: ${gl.getProgramInfoLog(program)}`);
      vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(program, "aPos");
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    } catch (e) {
      console.warn("[atlas] Prometheus avatar falling back to static rendering:", e);
      setFallback(true);
      return;
    }
    const u = {
      res: gl.getUniformLocation(program, "u_resolution"),
      time: gl.getUniformLocation(program, "u_time"),
      audio: gl.getUniformLocation(program, "u_audio"),
      state: gl.getUniformLocation(program, "u_state"),
      mix: gl.getUniformLocation(program, "u_state_mix"),
      energy: gl.getUniformLocation(program, "u_energy"),
      birth: gl.getUniformLocation(program, "u_birth_scale"),
    };

    const reduced = prefersReducedMotion();
    const s0 = live.current.state;
    let easing: Easing = { energy: s0 === "offline" ? OFFLINE_ENERGY : STATE_ENERGY[s0], mix: s0 === "adapting" ? 1 : 0 };
    let time = 0;
    let birthT = birth && !reduced ? 0 : 1;
    let audio = 0;
    let raf = 0;
    let last = performance.now();
    let visible = true;
    let pageVisible = document.visibilityState === "visible";
    let lost = false;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    };

    const draw = () => {
      if (!gl || lost) return;
      resize();
      const st = live.current.state;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.useProgram(program);
      gl.bindVertexArray(vao);
      gl.uniform2f(u.res, canvas.width, canvas.height);
      gl.uniform1f(u.time, time);
      gl.uniform1f(u.audio, st === "speaking" ? audio : 0);
      gl.uniform1i(u.state, st === "offline" ? 0 : stateIndex(st));
      gl.uniform1f(u.mix, easing.mix);
      gl.uniform1f(u.energy, easing.energy);
      // Star birth: ease-out scale from 0 to 1 over ~1.4 s.
      gl.uniform1f(u.birth, 1 - Math.pow(1 - Math.min(1, birthT), 3));
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };

    const frame = (now: number) => {
      raf = 0;
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      const st = live.current.state;
      // Offline: a still star. Otherwise wall-clock time, as in SolarSunWidget.advance_frame.
      if (st !== "offline") time += dt;
      birthT = Math.min(1, birthT + dt / 1.4);
      easing = ease(easing, st, dt);
      audio += (Math.max(0, Math.min(1, live.current.activity)) - audio) * Math.min(1, dt * 8);
      draw();
      schedule();
    };

    const schedule = () => {
      if (reduced || lost || raf || !visible || !pageVisible) return;
      last = performance.now();
      raf = requestAnimationFrame(frame);
    };
    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };

    // Reduced motion: jump straight to the target look and draw one still frame.
    const still = () => {
      const st = live.current.state;
      easing = { energy: st === "offline" ? OFFLINE_ENERGY : STATE_ENERGY[st], mix: st === "adapting" ? 1 : 0 };
      birthT = 1;
      draw();
    };
    redraw.current = reduced ? still : () => schedule();

    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver((entries) => {
          visible = entries.some((e) => e.isIntersecting);
          if (visible) schedule();
          else stop();
        })
      : null;
    io?.observe(canvas);
    const onVis = () => {
      pageVisible = document.visibilityState === "visible";
      if (pageVisible) schedule();
      else stop();
    };
    document.addEventListener("visibilitychange", onVis);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => (reduced ? still() : undefined)) : null;
    ro?.observe(canvas);
    const onLost = (e: Event) => {
      e.preventDefault();
      lost = true;
      stop();
      setFallback(true);
    };
    canvas.addEventListener("webglcontextlost", onLost);

    if (reduced) still();
    else schedule();

    return () => {
      stop();
      redraw.current = null;
      io?.disconnect();
      ro?.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      canvas.removeEventListener("webglcontextlost", onLost);
      if (gl && !lost) {
        gl.deleteBuffer(vbo);
        gl.deleteVertexArray(vao);
        gl.deleteProgram(program);
        gl.getExtension("WEBGL_lose_context")?.loseContext();
      }
    };
    // The GL setup runs once per mount; state changes flow through `live`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const label = `Prometheus — ${LABEL[state]}`;
  return (
    <div className={cn("relative overflow-hidden rounded-full", className)} style={{ width: size, height: size }} role="img" aria-label={label} data-avatar-state={state} data-avatar-render={fallback ? "static" : "webgl"}>
      {fallback ? (
        <div
          className={cn("size-full rounded-full", state === "offline" && "opacity-40 grayscale")}
          style={{
            background:
              state === "adapting"
                ? "radial-gradient(circle at 50% 50%, #b3ebff 0%, #1f99ff 22%, #0538c7 31%, rgba(5,46,166,0.35) 40%, #04070d 70%)"
                : "radial-gradient(circle at 50% 50%, #ffe08a 0%, #ff8a0d 22%, #c43a03 31%, rgba(196,58,3,0.35) 40%, #04070d 70%)",
          }}
        />
      ) : (
        <canvas ref={canvasRef} className="block size-full" />
      )}
    </div>
  );
}
