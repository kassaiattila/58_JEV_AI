// 261 (the consolidation round, DECISIONS 261): a notice a domain adds to a package's Processing section, with the action
// it offers (the email domain's: an email package from before 058 whose PDF attachments are not items yet). The shared
// section shows every registered notice in its place and runs the notice's action as its own buttons' (busy, its error
// in the section's message, then a reload), so a domain's notice behaves as the section's; until 261 the section named
// the email domain's call itself.
import type { ComponentType } from "react";
import type { WorkpackageView } from "../api";

export type ProcessNoticeProps = {
  view: WorkpackageView;
  /** a run is active or another action is under way */
  disabled: boolean;
  /** runs the notice's action as the section's own buttons do */
  run: (action: () => Promise<unknown>) => Promise<void>;
};

const NOTICES: ComponentType<ProcessNoticeProps>[] = [];

/** Registers a domain's notice (a domain's `index.tsx`, when the interface loads). */
export function registerProcessNotice(Notice: ComponentType<ProcessNoticeProps>): void {
  if (!NOTICES.includes(Notice)) NOTICES.push(Notice);
}

/** The registered notices, in the order the domains registered them. */
export function processNotices(): ComponentType<ProcessNoticeProps>[] {
  return [...NOTICES];
}
