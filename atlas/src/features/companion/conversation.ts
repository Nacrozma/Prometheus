import type { Message } from "@/lib/schemas";

/** "Ctrl" or "⌘" for shortcut labels. */
export const modKey = (): string => (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl");

/**
 * Whether the last reply can be regenerated in place. Mirrors the core's rule: there must be a
 * message to answer, and the reply after it must not have used tools (answering again could
 * repeat an action). The core enforces this; the UI only decides which button to show.
 */
export function canRegenerate(messages: Message[]): boolean {
  let lastUser = -1;
  messages.forEach((m, i) => {
    if (m.role === "user") lastUser = i;
  });
  if (lastUser < 0) return false;
  return !messages.slice(lastUser + 1).some((m) => m.role === "tool" || (m.parts ?? []).some((p) => p.type === "tool_call"));
}

/** True when the last message is a question with no reply after it (for example, the request failed). */
export function lastQuestionUnanswered(messages: Message[]): boolean {
  const said = messages.filter((m) => m.role !== "notice");
  return said.at(-1)?.role === "user";
}

/** The conversation as Markdown, for the clipboard. Tool traffic is summarised, not dumped. */
export function conversationToMarkdown(title: string, messages: Message[]): string {
  const out: string[] = [`# ${title}`];
  for (const m of messages) {
    if (m.role === "user") out.push(`## You\n\n${m.content.trim()}`);
    else if (m.role === "assistant") {
      const tools = (m.parts ?? []).filter((p) => p.type === "tool_call").map((p) => (p.type === "tool_call" ? p.name.replace("_", ".") : ""));
      const body = [m.content.trim(), tools.length ? `_Used: ${tools.join(", ")}_` : ""].filter(Boolean).join("\n\n");
      if (body) out.push(`## Atlas\n\n${body}`);
    } else if (m.role === "notice" && m.content.trim()) out.push(`> ${m.content.trim()}`);
  }
  return `${out.join("\n\n")}\n`;
}
