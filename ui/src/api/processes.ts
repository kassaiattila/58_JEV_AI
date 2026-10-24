// 231 (plan stage B, B2-B4; DECISIONS 231): the process packs and each one's own values (jav/app/process_settings.py):
// a value over a resource of its file (which price list, which template, how its letters are sent) or over a rule key
// its capabilities let it set (how many lines a quote holds, the rounding unit), every change a version: a draft,
// made active by the rule of who may, set aside to bring the file's value back; a rule value's preview on the
// process's traced decisions.
import { enc, request } from "./client";
import type { OutputTemplateState } from "./outputs";

export interface ProcessRow { id: string; title: string; version: string }
export interface SettingVersion {
  version: number; state: OutputTemplateState; value: string | number; note: string | null; made_by: string; made_at: string;
  activated_by: string | null; activated_at: string | null;
}
export interface ResourceSetting {
  key: string; label: string; options: { value: string; label: string }[] | null;
  file_value: string; value: string; own: boolean; versions: SettingVersion[];
}
export interface RuleSetting {
  key: string; file: string; path: string; what: string; kind: "int" | "choice"; least: number | null; most: number | null;
  options: string[]; steps: string[]; file_value: string | number; value: string | number; own: boolean; versions: SettingVersion[];
}
export interface ProcessSettings {
  pack: ProcessRow; resources: ResourceSetting[]; rules: RuleSetting[];
  partners: { role: string; label: string; step: string; step_title: string }[];
  policy: { activation: "editor" | "owner" | "second_person"; owners: string[] };
}
export interface RulePreview {
  key: string; value: string | number; file_value: string | number; decisions: number; changed: number; failed: number;
  first_error: string | null;
  examples: { point: string; subject: string; case_id: string; case: string; at: string; before: unknown; after: unknown }[];
}
export type SettingKind = "settings" | "rules";

const base = (pack: string, kind: SettingKind, key: string) => `/processes/${enc(pack)}/${kind}/${enc(key)}`;

export const processesApi = {
  processes: () => request<{ processes: ProcessRow[] }>("GET", "/processes"),
  processSettings: (pack: string) => request<ProcessSettings>("GET", `/processes/${enc(pack)}/settings`),
  proposeSetting: (pack: string, kind: SettingKind, key: string, value: string | number, note: string | null) =>
    request<ProcessSettings>("POST", base(pack, kind, key), { value, note }),
  activateSetting: (pack: string, kind: SettingKind, key: string, version: number) =>
    request<ProcessSettings>("POST", `${base(pack, kind, key)}/versions/${version}/activate`, {}),
  retireSetting: (pack: string, kind: SettingKind, key: string) =>
    request<ProcessSettings>("POST", `${base(pack, kind, key)}/retire`, {}),
  previewRule: (pack: string, key: string, value: string | number) =>
    request<RulePreview>("POST", `${base(pack, "rules", key)}/preview`, { value }),
};
