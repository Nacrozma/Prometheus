import { cn } from "@/lib/format";

/** Read-only unified diff with line colouring. Content is untrusted text and rendered as text. */
export function DiffView({ diff, className, empty = "No changes." }: { diff: string; className?: string; empty?: string }) {
  if (!diff.trim()) return <p className="px-3 py-6 text-center text-xs text-text-3">{empty}</p>;
  return (
    <pre className={cn("overflow-auto rounded-md border border-line-1 bg-bg-0 py-2 font-mono text-[0.72rem] leading-[1.55]", className)} aria-label="Diff">
      {diff.split("\n").map((line, i) => {
        const tone = line.startsWith("+++") || line.startsWith("---")
          ? "text-text-3"
          : line.startsWith("@@")
            ? "text-accent"
            : line.startsWith("+")
              ? "bg-ok-soft text-ok"
              : line.startsWith("-")
                ? "bg-err-soft text-err"
                : "text-text-2";
        return (
          <div key={i} className={cn("whitespace-pre px-3", tone)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
