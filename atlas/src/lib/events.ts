import { listen } from "@tauri-apps/api/event";
import { ChangeEventSchema, type Topic } from "./schemas";
import { isTauri } from "./bridge";

type Listener = (topic: Topic, id: string | null) => void;
const listeners = new Set<Listener>();
let started = false;

/** One Tauri subscription fans out to every interested component. */
function start() {
  if (started || !isTauri()) return;
  started = true;
  void listen<unknown>("atlas://changed", (e) => {
    const parsed = ChangeEventSchema.safeParse(e.payload);
    if (!parsed.success) return;
    for (const l of listeners) l(parsed.data.topic, parsed.data.id);
  });
}

export function onChange(l: Listener): () => void {
  start();
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Test hook: deliver a change as if it came from the core. */
export function emitLocal(topic: Topic, id: string | null = null) {
  for (const l of listeners) l(topic, id);
}
