import * as RadixTooltip from "@radix-ui/react-tooltip";
import { ChevronDown, Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-text-inverse font-semibold hover:brightness-110 active:brightness-95 shadow-[0_0_0_1px_rgb(125_243_255/0.25),0_6px_20px_rgb(60_207_230/0.18)]",
  secondary: "bg-bg-3 text-text-1 border border-line-2 hover:bg-bg-4 hover:border-line-3",
  ghost: "text-text-2 hover:text-text-1 hover:bg-bg-3",
  subtle: "bg-accent-softer text-accent-strong border border-line-2 hover:bg-accent-soft",
  danger: "bg-err-soft text-err border border-[color:var(--err)]/30 hover:bg-[color:var(--err)]/20",
};
const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5 rounded-sm",
  md: "h-9 px-3.5 text-sm gap-2 rounded-md",
  lg: "h-11 px-5 text-[0.95rem] gap-2.5 rounded-md",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap select-none transition-[background,color,border,filter,box-shadow] duration-[var(--dur-fast)] disabled:opacity-45 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function Tooltip({ label, children, side = "right" }: { label: ReactNode; children: ReactNode; side?: "top" | "right" | "bottom" | "left" }) {
  return (
    <RadixTooltip.Root delayDuration={350}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={8}
          className="z-50 rounded-sm border border-line-2 bg-bg-3 px-2 py-1 text-xs text-text-1 shadow-2 anim-fade"
        >
          {label}
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}

export const IconButton = forwardRef<HTMLButtonElement, ButtonProps & { label: string; tooltip?: boolean }>(function IconButton(
  { label, tooltip = true, className, size = "md", variant = "ghost", ...rest },
  ref,
) {
  const btn = (
    <Button
      ref={ref}
      aria-label={label}
      variant={variant}
      size={size}
      className={cn(size === "sm" ? "w-7 px-0" : size === "lg" ? "w-11 px-0" : "w-9 px-0", className)}
      {...rest}
    />
  );
  return tooltip ? <Tooltip label={label} side="bottom">{btn}</Tooltip> : btn;
});

const fieldBase =
  "w-full rounded-md border border-line-2 bg-bg-1 px-3 text-sm text-text-1 placeholder:text-text-3 transition-colors duration-[var(--dur-fast)] hover:border-line-3 focus:border-accent focus:outline-none focus-visible:outline-none focus:shadow-[0_0_0_3px_var(--accent-soft)] disabled:opacity-50";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(fieldBase, "h-9", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={cn(fieldBase, "py-2 leading-relaxed resize-y min-h-20", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...rest }, ref) {
  return (
    <span className={cn("relative inline-flex w-full", className?.match(/\b(w-\S+|max-w-\S+|flex-1)\b/g)?.join(" "))}>
      <select ref={ref} className={cn(fieldBase, "h-9 cursor-pointer appearance-none pr-8", className)} {...rest} />
      <ChevronDown aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-text-3" />
    </span>
  );
});

export function Switch({
  checked,
  onChange,
  label,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-[var(--dur-fast)] disabled:opacity-45",
        checked ? "bg-accent border-accent" : "bg-bg-4 border-line-2",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "inline-block size-3.5 rounded-full bg-white shadow transition-transform duration-[var(--dur-fast)]",
          checked ? "translate-x-[18px]" : "translate-x-[2px]",
        )}
      />
    </button>
  );
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-text-2">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-err">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-text-3">{hint}</p>
      ) : null}
    </div>
  );
}

export function Panel({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-lg border border-line-1 bg-bg-2/80 shadow-1", className)} {...rest}>
      {children}
    </div>
  );
}

export type Tone = "neutral" | "accent" | "ok" | "warn" | "err" | "info";
const tones: Record<Tone, string> = {
  neutral: "bg-bg-3 text-text-2 border-line-2",
  accent: "bg-accent-soft text-accent-strong border-line-2",
  ok: "bg-ok-soft text-ok border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  err: "bg-err-soft text-err border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-xs border px-1.5 py-0.5 text-[0.6875rem] font-medium leading-none", tones[tone], className)}>
      {children}
    </span>
  );
}

const dotTone: Record<Tone, string> = {
  neutral: "bg-text-3",
  accent: "bg-accent",
  ok: "bg-ok",
  warn: "bg-warn",
  err: "bg-err",
  info: "bg-info",
};

/** Status is always communicated with text, never color alone. */
export function StatusPill({ tone, label, pulse }: { tone: Tone; label: string; pulse?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-2">
      <span aria-hidden className={cn("size-1.5 rounded-full", dotTone[tone], pulse && "anim-pulse")} />
      {label}
    </span>
  );
}

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className={cn("inline-flex", className)}>
      <Loader2 className="size-4 animate-spin text-text-3" aria-hidden />
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("rounded-md bg-bg-3 anim-pulse", className)} />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-line-2 bg-bg-3 px-1 font-mono text-[0.65rem] text-text-2">
      {children}
    </kbd>
  );
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center anim-rise">
      {icon && <div className="grid size-12 place-items-center rounded-xl border border-line-2 bg-accent-softer text-accent">{icon}</div>}
      <h2 className="font-display text-md font-semibold text-text-1">{title}</h2>
      {body && <div className="max-w-md text-sm text-text-2">{body}</div>}
      {action}
    </div>
  );
}

export function ErrorNote({ title = "Something went wrong", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-[color:var(--err)]/25 bg-err-soft px-3.5 py-3 text-sm">
      <div className="flex-1">
        <p className="font-medium text-err">{title}</p>
        <p className="mt-0.5 text-text-2">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line-2 bg-bg-1 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "h-7 rounded-sm px-3 text-xs font-medium transition-colors duration-[var(--dur-fast)]",
            value === o.value ? "bg-bg-4 text-text-1 shadow-1" : "text-text-3 hover:text-text-1",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: string }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line-1 px-8 pb-5 pt-7">
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-accent">{eyebrow}</p>}
        <h1 className="font-display text-xl font-semibold text-text-1">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-text-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
