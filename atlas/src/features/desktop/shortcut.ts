/** Turn a key press into a shortcut string like "Ctrl+Alt+Space" (or null while only modifiers are held). */
export function shortcutFromEvent(e: Pick<KeyboardEvent, "ctrlKey" | "altKey" | "shiftKey" | "metaKey" | "code" | "key">): string | null {
  const mods = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Super"].filter(Boolean) as string[];
  const key = keyName(e.code);
  if (!key || mods.length === 0) return null;
  return [...mods, key].join("+");
}

const NAMED: Record<string, string> = {
  Space: "Space",
  Enter: "Enter",
  Tab: "Tab",
  Backspace: "Backspace",
  Insert: "Insert",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Backquote: "Backquote",
  Minus: "Minus",
  Equal: "Equal",
  Comma: "Comma",
  Period: "Period",
  Slash: "Slash",
  Semicolon: "Semicolon",
};

function keyName(code: string): string | null {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  return NAMED[code] ?? null;
}

/** "Ctrl+Alt+Space" → ["Ctrl", "Alt", "Space"], with the Windows key named for people. */
export function shortcutParts(s: string): string[] {
  return s.split("+").map((p) => (p === "Super" ? "Win" : p));
}
