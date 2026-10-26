// 231 (plan stage C, C3e; DECISIONS 231): the views of a package's Result section, in their order (the service says
// which hold data). The shared ones are listed here; a domain registers its own when the interface loads
// (`ui/src/domains/`), with a panel shown above its table, so the Result section and the address bar name no domain's
// view. Until C3e the list was the Result section's own (`views/ResultStage.tsx` `TABLES`). The labels stand as source
// texts (Hungarian ones from before 073), translated when shown.
import type { ComponentType } from "react";

export interface ResultTableSpec {
  key: string;
  /** the dataset its table shows (`configs/datasets.json`) */
  dataset: string;
  label: string;
  /** its place among the views (the shared ones step by ten, so a domain's falls between them) */
  order: number;
  /** shown above the table: the package's (`wpId`) or a run's (`runId`) own summary of the view */
  Panel?: ComponentType<{ wpId: string; runId?: string }>;
}

const SHARED: ResultTableSpec[] = [
  { key: "emails", dataset: "emails", label: "Levelek", order: 10 },
  { key: "tasks", dataset: "email_tasks", label: "Feladatok", order: 20 },
  { key: "documents", dataset: "documents", label: "Iratok", order: 30 },
  { key: "datapoints", dataset: "datapoints", label: "Adatpontok", order: 40 },
  { key: "native_facts", dataset: "native_facts", label: "Native facts", order: 50 },
  { key: "line_items", dataset: "line_items", label: "Tételsorok", order: 60 },
  { key: "file_names", dataset: "file_names", label: "Fájlnevek", order: 80 },
];
const OWN = new Map<string, ResultTableSpec>();

/** Registers a domain's view (a second registration of the same key replaces the first). */
export function registerResultTable(spec: ResultTableSpec): void {
  OWN.set(spec.key, spec);
}

/** Every view, in its order. */
export function resultTables(): ResultTableSpec[] {
  return [...SHARED, ...OWN.values()].sort((a, b) => a.order - b.order);
}
