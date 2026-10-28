// 231 (plan stage B, B2-B4; DECISIONS 231): the process packs and each one's own values (jav/app/process_settings.py):
// a value over a resource of its file (which price list, which template, how its letters are sent) or over a rule key
// its capabilities let it set (how many lines a quote holds, the rounding unit), every change a version: a draft,
// made active by the rule of who may, set aside to bring the file's value back; a rule value's preview on the
// process's traced decisions.
import { enc, request } from "./client";
import type { OutputTemplateState } from "./outputs";

export interface ProcessRow {
  id: string; title: string; version: string;
  /** 231 (C1c): the scope parts a case needs, and the kinds of package whose page offers one; (C2d) the parts a person
   *  gives (the others take their default) */
  scope?: string[]; package_kinds?: string[]; asks?: string[];
  /** 231 (C3d): the source kinds its case's documents may come from (a folder, files, a mailbox download) */
  source_kinds?: string[];
  /** 231 (U2c): the steps whose case of another process takes its own documents (each its source kinds, and whether
   *  that process has invented documents to start on) */
  step_sources?: StepSource[];
  /** 231 (U0): whether a person may start a case by hand, what the process is for, what a case of it cannot start
   *  without now (a resource it needs at its start with no active version), and whether it has example material */
  manual?: boolean; summary?: string | null; missing_at_start?: { key: string; label: string }[]; examples?: boolean;
}
/** 231 (U2c): a step of a multi-step process whose sub-case takes its own documents. */
export interface StepSource {
  step: string; title: string; pack: string; process: string; source_kinds: string[]; examples: boolean;
}
/** 231 (U0): a process's example material: the sets of things it installs (each `installed`, `partial` or `missing`;
 *  `example`: the examples' machine made all that is there) and its packets of invented documents; (U1e) the pack's
 *  sentence on how the material is tried. */
export interface ProcessExamples {
  sets: { kind: string; name: string; title: string; state: "installed" | "partial" | "missing"; example: boolean }[];
  packets: { id: string; title: string; documents: number }[];
  note?: string;
}
/** 231 (C3c): a record a case may start from (an email or a document read as the pack's record), with the cases
 *  already started from it; `detail` holds plain values (its customer, package, day). */
export interface ProcessRecord {
  workpackage_id: string; workpackage_name: string; item_id: string; label: string | null; detail: string; name: string | null;
  cases: { id: string; name: string }[];
}
/** 231 (C1c): a process whose case may read a package (`jav/app/intake.py` `package_offers`). */
export interface PackageOffer {
  pack: string; title: string; name: string; sources: string[]; cases: { id: string; name: string }[];
  package_name?: string;  // 231 (U1): the package's own name, so the case is named with the title in the interface's language
}
export interface SettingVersion {
  version: number; state: OutputTemplateState; value: string | number; note: string | null; made_by: string; made_at: string;
  activated_by: string | null; activated_at: string | null;
}
export interface ResourceSetting {
  key: string; label: string; options: { value: string; label: string }[] | null;
  file_value: string; value: string; own: boolean; versions: SettingVersion[];
  /** 231 (U3c): the resource it follows from (a product brings its tariff), shown read only */
  derived_from?: string | null;
}
export interface RuleSetting {
  key: string; file: string; path: string; what: string; kind: "int" | "choice"; least: number | null; most: number | null;
  options: string[]; steps: string[]; file_value: string | number; value: string | number; own: boolean; versions: SettingVersion[];
}
export interface ProcessSettings {
  pack: ProcessRow; resources: ResourceSetting[]; rules: RuleSetting[];
  partners: { role: string; label: string; step: string; step_title: string }[];
  policy: { activation: "editor" | "owner" | "second_person"; owners: string[] };
  /** 231 (U3a): what the process is for, its steps, outputs, golden sets, what starts a case of it, its examples */
  description: ProcessDescription;
}
/** 231 (U3a): a process described on its own settings page (jav/app/process_settings.py `_description`). */
export interface ProcessDescription {
  summary: string | null;
  steps: { id: string; title: string; uses: string; summary: string; start: "auto" | "person"; after: string[]; optional: boolean }[];
  outputs: { id: string; what: string | null; format: string | null }[];
  goldens: string[];
  intake: { on: "email_intent" | "package" | "manual"; starts: "offer" | "case" | "manual"; intent: string | null }[];
  examples: boolean;
}
export interface RulePreview {
  key: string; value: string | number; file_value: string | number; decisions: number; changed: number; failed: number;
  first_error: string | null;
  examples: { point: string; subject: string; case_id: string; case: string; at: string; before: unknown; after: unknown }[];
}
export type SettingKind = "settings" | "rules";
/** 231 (U3d): the kinds of shared things the processes name, and for each thing of a kind the processes using it */
export type LibraryKind = "product" | "tariff" | "price_list" | "letter_frame" | "quote_letter_frame" | "output_template" | "partner_role";
export type UsedByMap = Record<string, { id: string; title: string }[]>;
/** 231 (U3f): the letter frames of the shared library (jav/app/letter_frames.py): each kind's frames with the file's
 *  text, the text in effect (its active version's, else the file's) and its versions; the fields a person edits. */
export type FrameContent = Record<string, unknown>;
export interface FrameField { path: string; label: string; form: "line" | "text" | "paragraphs"; group: string | null }
export interface FrameVersion {
  version: number; state: OutputTemplateState; content: FrameContent; note: string | null; made_by: string; made_at: string;
  activated_by: string | null; activated_at: string | null;
}
export interface LetterFrame { ident: string; file: FrameContent; content: FrameContent; active: number | null; markers: string[]; versions: FrameVersion[] }
export interface LetterFrameKind { kind: LibraryKind; title: string; what: string; fields: FrameField[]; frames: LetterFrame[]; markers: string[] }
export interface LetterFrames { kinds: LetterFrameKind[]; policy: { activation: string; owners: string[] } }
const frameBase = (kind: string, ident: string) => `/library/letter-frames/${enc(kind)}/${enc(ident)}`;

const base = (pack: string, kind: SettingKind, key: string) => `/processes/${enc(pack)}/${kind}/${enc(key)}`;

export const processesApi = {
  processes: () => request<{ processes: ProcessRow[] }>("GET", "/processes"),
  /** 231 (C3c): the records a case of the pack may start from (the general form's record chooser) */
  processRecords: (pack: string, q?: string) =>
    request<{ records: ProcessRecord[] }>("GET", `/processes/${enc(pack)}/records${q ? `?q=${enc(q)}` : ""}`),
  processSettings: (pack: string) => request<ProcessSettings>("GET", `/processes/${enc(pack)}/settings`),
  proposeSetting: (pack: string, kind: SettingKind, key: string, value: string | number, note: string | null) =>
    request<ProcessSettings>("POST", base(pack, kind, key), { value, note }),
  activateSetting: (pack: string, kind: SettingKind, key: string, version: number) =>
    request<ProcessSettings>("POST", `${base(pack, kind, key)}/versions/${version}/activate`, {}),
  retireSetting: (pack: string, kind: SettingKind, key: string) =>
    request<ProcessSettings>("POST", `${base(pack, kind, key)}/retire`, {}),
  previewRule: (pack: string, key: string, value: string | number) =>
    request<RulePreview>("POST", `${base(pack, "rules", key)}/preview`, { value }),
  /** 231 (U0): the example material, its installation and removal, and a packet's documents written as files */
  processExamples: (pack: string) => request<ProcessExamples>("GET", `/processes/${enc(pack)}/examples`),
  installExamples: (pack: string) => request<ProcessExamples>("POST", `/processes/${enc(pack)}/examples/install`, {}),
  removeExamples: (pack: string) => request<ProcessExamples>("POST", `/processes/${enc(pack)}/examples/remove`, {}),
  examplePacketFiles: (pack: string, packet: string) =>
    request<{ files: string[] }>("POST", `/processes/${enc(pack)}/examples/packets/${enc(packet)}/files`, {}),
  usedBy: (kind: LibraryKind) => request<{ used_by: UsedByMap }>("GET", `/library/used-by/${enc(kind)}`),
  letterFrames: () => request<LetterFrames>("GET", "/library/letter-frames"),
  proposeLetterFrame: (kind: string, ident: string, values: Record<string, string | string[]>, note: string | null) =>
    request<LetterFrames>("POST", frameBase(kind, ident), { values, note }),
  activateLetterFrame: (kind: string, ident: string, version: number) =>
    request<LetterFrames>("POST", `${frameBase(kind, ident)}/versions/${version}/activate`, {}),
  retireLetterFrame: (kind: string, ident: string) => request<LetterFrames>("POST", `${frameBase(kind, ident)}/retire`, {}),
};
