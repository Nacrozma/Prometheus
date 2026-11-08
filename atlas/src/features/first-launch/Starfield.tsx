import { useEffect, useRef } from "react";

type Star = { x: number; y: number; r: number; a: number; tw: number; ph: number; dx: number; dy: number; tint: boolean };

/**
 * Ambient stars on a 2D canvas. Sharp at any DPI; pauses while the window is hidden; drawn once
 * and left still under reduced motion. Cleans up its animation frame and listeners on unmount.
 */
export function Starfield({ reduced, className }: { reduced: boolean; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return; // no canvas support: the gradient background still shows
    let stars: Star[] = [];
    let raf = 0;
    let w = 0;
    let h = 0;

    const build = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.min(220, Math.round((w * h) / 9000));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: 0.35 + Math.random() ** 2 * 1.25,
        a: 0.25 + Math.random() * 0.65,
        tw: 0.4 + Math.random() * 1.2,
        ph: Math.random() * Math.PI * 2,
        dx: -0.004 - Math.random() * 0.006,
        dy: -0.002 - Math.random() * 0.004,
        tint: Math.random() < 0.55,
      }));
    };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        const twinkle = reduced ? 1 : 0.72 + 0.28 * Math.sin(t * 0.001 * s.tw + s.ph);
        ctx.fillStyle = s.tint ? `rgba(158,235,255,${(s.a * twinkle).toFixed(3)})` : `rgba(235,246,255,${(s.a * twinkle).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    let last = performance.now();
    const frame = (t: number) => {
      const dt = Math.min(64, t - last);
      last = t;
      for (const s of stars) {
        s.x += s.dx * dt;
        s.y += s.dy * dt;
        if (s.x < -2) s.x = w + 2;
        if (s.y < -2) s.y = h + 2;
      }
      draw(t);
      raf = requestAnimationFrame(frame);
    };
    const start = () => {
      cancelAnimationFrame(raf);
      if (reduced) draw(0);
      else if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    const onVisibility = () => (document.hidden ? cancelAnimationFrame(raf) : start());
    const onResize = () => {
      build();
      start();
    };

    build();
    start();
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [reduced]);

  return <canvas ref={ref} aria-hidden className={className} />;
}
