import { Check, Copy } from "lucide-react";
import { memo, useState, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { api, isTauri } from "@/lib/bridge";

/**
 * Renders untrusted model output. Raw HTML is never rendered (no rehype-raw), URLs pass through
 * react-markdown's sanitising transform, links open only on an explicit click in the system
 * browser, and remote images are shown as links instead of being fetched.
 */
function safeUrl(url: string): string {
  const u = defaultUrlTransform(url);
  return /^https?:\/\//i.test(u) ? u : "";
}

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      aria-label={done ? "Copied" : label}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        });
      }}
      className="inline-flex items-center gap-1 rounded-xs px-1.5 py-0.5 text-[0.6875rem] text-text-3 hover:bg-bg-4 hover:text-text-1"
    >
      {done ? <Check className="size-3.5 text-ok" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {done ? "Copied" : label}
    </button>
  );
}

const components: Components = {
  a({ href, children }) {
    const url = safeUrl(href ?? "");
    if (!url) return <span className="text-text-2">{children}</span>;
    return (
      <a
        href={url}
        title={url}
        rel="noreferrer noopener"
        onClick={(e) => {
          e.preventDefault();
          if (isTauri()) void api.openExternal(url);
        }}
      >
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    const url = typeof src === "string" ? safeUrl(src) : "";
    return url ? (
      <a
        href={url}
        onClick={(e) => {
          e.preventDefault();
          if (isTauri()) void api.openExternal(url);
        }}
      >
        [image: {alt || url}]
      </a>
    ) : (
      <span>[image: {alt}]</span>
    );
  },
  pre({ children }) {
    const child = Array.isArray(children) ? children[0] : children;
    const className = (child && typeof child === "object" && "props" in child ? (child.props as { className?: string }).className : "") ?? "";
    const lang = /language-(\S+)/.exec(className)?.[1] ?? "text";
    const code = textOf(children).replace(/\n$/, "");
    return (
      <div className="my-3 overflow-hidden rounded-md border border-line-2 bg-[color:var(--code-bg)]">
        <div className="flex items-center justify-between border-b border-line-1 px-3 py-1">
          <span className="font-mono text-[0.6875rem] uppercase tracking-wider text-text-3">{lang}</span>
          <CopyButton text={code} />
        </div>
        <pre className="overflow-x-auto px-3.5 py-3 font-mono text-[0.8125rem] leading-relaxed">{children}</pre>
      </div>
    );
  },
};

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-atlas">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeHighlight, { detect: false, ignoreMissing: true }]]} components={components} urlTransform={safeUrl}>
        {text}
      </ReactMarkdown>
    </div>
  );
});
