// Compiles the Prometheus solar shader in a real WebGL2 context (Chromium) and renders each state.
// Usage: node tests/visual/avatar-webgl.mjs <out-dir>
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

// Playwright is used from the machine's global install (not a project dependency).
const { chromium } = createRequire(import.meta.url)("playwright");

const out = process.argv[2] ?? "test-results/avatar";
fs.mkdirSync(out, { recursive: true });
const src = fs.readFileSync(new URL("../../src/features/siblings/avatar/solarShader.ts", import.meta.url), "utf8");
const pick = (name) => src.split(`export const ${name} = \``)[1].split("`;")[0];
const VS = pick("VERTEX_SHADER");
const FS = pick("FRAGMENT_SHADER");

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 320, height: 320 } });
await page.setContent(`<canvas id="c" width="320" height="320" style="display:block"></canvas>`);
const states = [["idle", 0, 0.55, 0], ["thinking", 1, 1.08, 0], ["speaking", 2, 1.6, 0], ["adapting", 3, 1.5, 1]];
const result = await page.evaluate(([VS, FS]) => {
  const gl = document.getElementById("c").getContext("webgl2");
  if (!gl) return { error: "no webgl2" };
  const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(p, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) return { error: gl.getProgramInfoLog(p) };
  window.__gl = { gl, p };
  return { ok: true, renderer: gl.getParameter(gl.RENDERER) };
}, [VS, FS]);
if (!result.ok) { console.error("FAILED", result); process.exit(1); }
console.log("compiled and linked on", result.renderer);
for (const [name, idx, energy, mix] of states) {
  const centre = await page.evaluate(([idx, energy, mix]) => {
    const { gl, p } = window.__gl;
    gl.useProgram(p);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const l = gl.getAttribLocation(p, "aPos"); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
    const u = (n) => gl.getUniformLocation(p, n);
    gl.uniform2f(u("u_resolution"), 320, 320); gl.uniform1f(u("u_time"), 12.5); gl.uniform1f(u("u_audio"), idx === 2 ? 0.6 : 0);
    gl.uniform1i(u("u_state"), idx); gl.uniform1f(u("u_state_mix"), mix); gl.uniform1f(u("u_energy"), energy); gl.uniform1f(u("u_birth_scale"), 1);
    gl.viewport(0, 0, 320, 320); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    const px = new Uint8Array(4); gl.readPixels(160, 160, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    return Array.from(px);
  }, [idx, energy, mix]);
  await page.screenshot({ path: path.join(out, `avatar-${name}.png`) });
  console.log(name, "centre pixel", centre.join(","));
  // The star's core must be lit and coloured: gold (red > blue) normally, cobalt (blue > red) when adapting.
  if (centre[0] + centre[1] + centre[2] < 120) { console.error(`${name}: core is dark`); process.exit(1); }
  if (name === "adapting" ? centre[2] <= centre[0] : centre[0] <= centre[2]) { console.error(`${name}: wrong palette`); process.exit(1); }
}
await browser.close();
