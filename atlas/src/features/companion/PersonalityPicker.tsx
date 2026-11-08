import { cn } from "@/lib/format";
import type { Personality } from "@/lib/schemas";

/** The presets as shown to the owner. The core owns what each one means (tone, length, initiative, style). */
export const PERSONALITIES: { value: Personality; label: string; hint: string }[] = [
  { value: "professional", label: "Professional", hint: "Clear, courteous and businesslike" },
  { value: "friendly", label: "Friendly", hint: "Warm and conversational; suggests next steps" },
  { value: "analytical", label: "Analytical", hint: "Structured; states assumptions and quantifies" },
  { value: "concise", label: "Concise", hint: "Answer first, no preamble" },
  { value: "detailed", label: "Detailed", hint: "Thorough, with examples and edge cases" },
  { value: "creative", label: "Creative", hint: "Imaginative; offers alternatives" },
  { value: "custom", label: "Custom", hint: "Your own tone, length and initiative" },
];

export function PersonalityPicker({ value, onChange, includeCustom = true }: { value: Personality; onChange: (p: Personality) => void; includeCustom?: boolean }) {
  const options = PERSONALITIES.filter((p) => includeCustom || p.value !== "custom" || value === "custom");
  return (
    <div role="radiogroup" aria-label="Personality" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {options.map((p) => {
        const on = p.value === value;
        return (
          <button
            key={p.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(p.value)}
            className={cn(
              "rounded-lg border px-3.5 py-2.5 text-left transition-colors",
              on ? "border-accent bg-accent-soft text-text-1" : "border-line-1 bg-bg-2/70 text-text-2 hover:border-line-3 hover:bg-bg-3 hover:text-text-1",
            )}
          >
            <span className="block text-sm font-medium">{p.label}</span>
            <span className="mt-0.5 block text-xs text-text-3">{p.hint}</span>
          </button>
        );
      })}
    </div>
  );
}
