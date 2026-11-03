import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/format";
import { Button, Input } from "./primitives";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-[color:var(--bg-overlay)] backdrop-blur-[2px] anim-fade" />
        <D.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line-2 bg-bg-2 shadow-3 anim-rise",
            width,
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line-1 px-5 py-4">
            <div>
              <D.Title className="font-display text-md font-semibold text-text-1">{title}</D.Title>
              {description ? (
                <D.Description className="mt-1 text-sm text-text-2">{description}</D.Description>
              ) : (
                <D.Description className="sr-only">{title}</D.Description>
              )}
            </div>
            <D.Close asChild>
              <button aria-label="Close" className="rounded-sm p-1 text-text-3 hover:bg-bg-3 hover:text-text-1">
                <X className="size-4" />
              </button>
            </D.Close>
          </div>
          {children && <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>}
          {footer && <div className="flex justify-end gap-2 border-t border-line-1 px-5 py-3">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

/** Confirmation with an optional typed phrase for irreversible actions. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  danger,
  typeToConfirm,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  typeToConfirm?: string;
  onConfirm: () => Promise<void> | void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = !typeToConfirm || typed === typeToConfirm;
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setTyped("");
        onOpenChange(v);
      }}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={danger ? "danger" : "primary"}
            disabled={!ready}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                setTyped("");
                onOpenChange(false);
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-text-2">
        {body}
        {typeToConfirm && (
          <label className="block">
            <span className="text-xs text-text-3">
              Type <strong className="font-mono text-text-1">{typeToConfirm}</strong> to confirm
            </span>
            <Input className="mt-1.5" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus aria-label="Confirmation text" />
          </label>
        )}
      </div>
    </Dialog>
  );
}
