const acronyms = new Set(["ap", "cnil", "csv", "dpc", "hhs", "ico", "id", "ipc", "mndb", "ndb", "nsw", "oaic", "uk", "us"]);

export function label(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w+\b/g, (word) => acronyms.has(word.toLowerCase())
      ? word.toUpperCase()
      : word[0]!.toUpperCase() + word.slice(1));
}

export function date(value: string | null | undefined): string {
  if (!value) return "Not published";
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en-AU").format(value);
}
