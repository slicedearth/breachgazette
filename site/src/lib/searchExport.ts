import type { Notification } from "./types";

export const csvCell = (value: string | number | null | undefined) => {
  let text = String(value ?? "");
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
};

export function notificationCsv(records: readonly Notification[]): string {
  const headers = [
    "source_id",
    "source_record_id",
    "named_entity",
    "source_role",
    "jurisdiction",
    "regulator",
    "reporting_scheme",
    "source_dates",
    "publication_level",
    "affected_population",
    "information_categories",
    "breach_cause",
    "source_url",
  ];
  const rows = records.map((record) => [
    record.source_id,
    record.source_record_id,
    record.named_entity.source_name,
    record.named_entity.role,
    record.jurisdiction,
    record.regulator,
    record.reporting_scheme,
    record.dates
      .map((item) => item.normalized_date)
      .filter(Boolean)
      .join("; "),
    record.publication_level,
    record.affected_population?.count,
    record.information_categories
      .map((item) => item.normalized_label)
      .join("; "),
    record.breach_cause?.normalized_label,
    record.source_url,
  ]);
  return [
    headers.map(csvCell).join(","),
    ...rows.map((row) => row.map(csvCell).join(",")),
  ].join("\r\n");
}
