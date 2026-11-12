import type { Todo } from "@/lib/schemas";

const DAY = 86_400_000;
const parse = (iso: string) => new Date(`${iso}T00:00:00`);
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Whole days from `today` to `date` (both YYYY-MM-DD, local). */
export function daysFrom(today: string, date: string): number {
  return Math.round((parse(date).getTime() - parse(today).getTime()) / DAY);
}

export function addDays(date: string, n: number): string {
  const d = parse(date);
  d.setDate(d.getDate() + n);
  return iso(d);
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Today", "Tomorrow", "Yesterday", "Friday" (within a week), otherwise "Fri 20 Nov" (with the year if different). */
export function dayLabel(date: string, today: string): string {
  const n = daysFrom(today, date);
  if (n === 0) return "Today";
  if (n === 1) return "Tomorrow";
  if (n === -1) return "Yesterday";
  const d = parse(date);
  const weekday = WEEKDAYS[d.getDay()] ?? "";
  if (n > 1 && n < 7) return weekday;
  const year = d.getFullYear() === parse(today).getFullYear() ? "" : ` ${d.getFullYear()}`;
  return `${weekday.slice(0, 3)} ${d.getDate()} ${MONTHS[d.getMonth()]}${year}`;
}

/** A task's deadline in words: "Today 17:00", "Friday", "Fri 20 Nov 09:30". */
export function dueLabel(t: Pick<Todo, "due_date" | "due_time">, today: string): string | null {
  if (!t.due_date) return null;
  return t.due_time ? `${dayLabel(t.due_date, today)} ${t.due_time}` : dayLabel(t.due_date, today);
}

export const REPEAT_LABEL: Record<Todo["recurrence"], string> = {
  none: "Does not repeat",
  daily: "Every day",
  weekdays: "Every weekday",
  weekly: "Every week",
  monthly: "Every month",
  yearly: "Every year",
};

export interface Group {
  key: string;
  label: string;
  tone: "err" | "accent" | "neutral";
  items: Todo[];
}

/** Group open tasks for the day and week views: Overdue first, then each day, then "No date". */
export function groupByDay(items: Todo[], today: string): Group[] {
  const groups = new Map<string, Group>();
  const put = (key: string, label: string, tone: Group["tone"], t: Todo) => {
    const g = groups.get(key) ?? { key, label, tone, items: [] };
    g.items.push(t);
    groups.set(key, g);
  };
  for (const t of items) {
    if (!t.due_date) put("~none", "No date", "neutral", t);
    else if (t.due_date < today) put("!overdue", "Overdue", "err", t);
    else put(t.due_date, dayLabel(t.due_date, today), t.due_date === today ? "accent" : "neutral", t);
  }
  // Plain code-point order: "!overdue" < dates < "~none" (locale collation would reorder the symbols).
  return [...groups.values()].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}
