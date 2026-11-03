import { useEffect, useState } from "react";
import { cn } from "@/lib/format";

/** True when the user (OS or app setting) prefers reduced motion. */
export function useReducedMotion(): boolean {
  const read = () => {
    const pref = document.documentElement.dataset.motion;
    if (pref === "reduced") return true;
    if (pref === "full") return false;
    return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  };
  const [reduced, setReduced] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(read());
    mq?.addEventListener("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-motion"] });
    return () => {
      mq?.removeEventListener("change", update);
      obs.disconnect();
    };
  }, []);
  return reduced;
}

const ORBIT = "M -240 0 A 240 72 0 1 1 240 0 A 240 72 0 1 1 -240 0";

/** The Atlas globe-and-orbit mark. `animated` moves the satellite along its orbit (off under reduced motion). */
export function Emblem({ size = 32, animated = false, className, glow = false }: { size?: number; animated?: boolean; className?: string; glow?: boolean }) {
  const reduced = useReducedMotion();
  const moving = animated && !reduced;
  return (
    <svg
      width={size}
      height={size}
      viewBox="-300 -300 600 600"
      className={cn(className, glow && "drop-shadow-[0_0_18px_rgb(60_207_230/0.45)]")}
      role="img"
      aria-label="ATLAS emblem"
    >
      <defs>
        <linearGradient id="em-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9EEBFF" />
          <stop offset="0.5" stopColor="#3CCFE6" />
          <stop offset="1" stopColor="#1C8FB8" />
        </linearGradient>
        <linearGradient id="em-o" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#5EEAD4" stopOpacity="0.1" />
          <stop offset="0.5" stopColor="#7DF3FF" />
          <stop offset="1" stopColor="#5EEAD4" stopOpacity="0.1" />
        </linearGradient>
      </defs>
      <circle r="150" fill="url(#em-g)" opacity="0.1" />
      <circle r="150" fill="none" stroke="url(#em-g)" strokeWidth="16" />
      <ellipse rx="62" ry="150" fill="none" stroke="#7DE6F5" strokeOpacity="0.75" strokeWidth="9" />
      <line x1="-150" x2="150" stroke="#7DE6F5" strokeOpacity="0.75" strokeWidth="9" />
      <g transform="rotate(-22)">
        <path d={ORBIT} fill="none" stroke="url(#em-o)" strokeWidth="10" />
        <g transform={moving ? undefined : "translate(194 -42)"}>
          <circle r="34" fill="#7DF3FF" opacity="0.25" />
          <circle r="16" fill="#fff" />
          {moving && <animateMotion dur="9s" repeatCount="indefinite" path={ORBIT} />}
        </g>
      </g>
    </svg>
  );
}
