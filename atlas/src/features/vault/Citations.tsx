import { BookOpen, ShieldAlert } from "lucide-react";
import type { VaultSource } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { locationLabel } from "./Vault";

/** Citation markers ([S1]…) in a reply that match no passage actually sent with the question. */
export function unknownCitations(reply: string, sources: VaultSource[]): string[] {
  const found = new Set<string>();
  for (const m of reply.matchAll(/\[(S\d{1,3})\]/g)) {
    const label = m[1] ?? "";
    if (!sources.some((s) => s.label === label && s.sent)) found.add(label);
  }
  return [...found].sort();
}

/**
 * The Knowledge Vault passages a reply was given, each opening the document at that passage. Only
 * passages Atlas really retrieved are listed; a marker in the reply that matches none of them is
 * flagged instead of being shown as a source.
 */
export function SourceList({ sources, reply }: { sources: VaultSource[]; reply: string }) {
  const open = useUi((s) => s.openVaultSource);
  if (!sources.length) return null;
  const sent = sources.filter((s) => s.sent);
  const held = sources.filter((s) => !s.sent);
  const unknown = unknownCitations(reply, sources);
  const cited = new Set([...reply.matchAll(/\[(S\d{1,3})\]/g)].map((m) => m[1]));
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-line-2 bg-bg-2/60 px-3 py-2 text-xs" data-sources aria-label="Sources from your Knowledge Vault">
      <p className="flex items-center gap-1.5 font-medium text-text-2">
        <BookOpen className="size-3.5 text-accent" aria-hidden />
        {sent.length ? `Answered with ${sent.length} ${sent.length === 1 ? "passage" : "passages"} from your Knowledge Vault` : "Relevant passages were found but not sent"}
      </p>
      <ul className="flex flex-col gap-1">
        {[...sent, ...held].map((s) => (
          <li key={s.label} className="flex items-baseline gap-2" data-source={s.label} data-cited={cited.has(s.label) ? "true" : "false"}>
            <span className="w-7 shrink-0 font-mono text-accent">[{s.label}]</span>
            {s.document_id ? (
              <button type="button" className="min-w-0 truncate text-left text-text-1 hover:underline" onClick={() => open({ documentId: s.document_id!, chunkId: s.chunk_id, page: s.page, heading: s.heading })}>
                {s.title}
              </button>
            ) : (
              <span className="min-w-0 truncate text-text-3 line-through" title="This document has since been removed from the Vault">
                {s.title}
              </span>
            )}
            <span className="shrink-0 text-text-3">{locationLabel(s.page, s.heading)}</span>
            {!s.sent && <span className="shrink-0 text-warn">held back (local-only)</span>}
            {!s.document_id && <span className="shrink-0 text-text-3">removed</span>}
          </li>
        ))}
      </ul>
      {unknown.length > 0 && (
        <p className="flex items-center gap-1.5 text-warn" data-unknown-citations>
          <ShieldAlert className="size-3.5" aria-hidden />
          The reply mentions {unknown.map((u) => `[${u}]`).join(", ")}, which {unknown.length === 1 ? "is" : "are"} not among the passages it was given. Treat {unknown.length === 1 ? "that citation" : "those citations"} as unsupported.
        </p>
      )}
    </div>
  );
}
