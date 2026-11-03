import { ArrowUp, Paperclip, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button, IconButton } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";

export function Composer({
  running,
  disabled,
  disabledReason,
  onSend,
  onStop,
  autoFocus,
}: {
  running: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onSend: (text: string) => void;
  onStop: () => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  const submit = () => {
    const t = text.trim();
    if (!t || running || disabled) return;
    onSend(t);
    setText("");
  };

  const attach = async () => {
    try {
      const g = await api.shareFile();
      if (!g) return;
      setText((t) => `${t}${t && !t.endsWith("\n") ? "\n" : ""}[Shared file “${g.label}” — grant_id: ${g.id}] `);
      toast.success(`Shared “${g.label}” with Atlas for reading`);
      ref.current?.focus();
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not share the file");
    }
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-6 pb-5">
      <div className="rounded-xl border border-line-2 bg-bg-2 shadow-2 transition-[border,box-shadow] focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]">
        <label htmlFor="composer" className="sr-only">
          Message Atlas
        </label>
        <textarea
          id="composer"
          ref={ref}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={disabled ? disabledReason : "Ask Atlas anything…"}
          className="block max-h-[260px] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-sm leading-relaxed text-text-1 outline-none focus-visible:outline-none placeholder:text-text-3 disabled:cursor-not-allowed"
        />
        <div className="flex items-center gap-1 px-2 pb-2">
          <IconButton label="Share a text file with Atlas" size="sm" onClick={attach} disabled={disabled}>
            <Paperclip className="size-4" aria-hidden />
          </IconButton>
          <span className="ml-1 hidden text-[0.6875rem] text-text-3 sm:inline">Enter to send · Shift+Enter for a new line</span>
          <div className="ml-auto">
            {running ? (
              <Button size="sm" variant="danger" onClick={onStop} icon={<Square className="size-3.5" aria-hidden />}>
                Stop
              </Button>
            ) : (
              <Button size="sm" variant="primary" onClick={submit} disabled={!text.trim() || disabled} icon={<ArrowUp className="size-4" aria-hidden />}>
                Send
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
