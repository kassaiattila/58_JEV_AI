// 263 (plan E, E1; the owner's decision of 2026-10-30: a page's main action at the right end of its title row): a part
// of a page that has the page's main action (a section of Settings: "New partner") puts it into the page header's
// actions, not into a row of its own; the header gives the place (`PageHeader` `actionsSlot`), the part fills it.
import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

const Slot = createContext<HTMLElement | null>(null);

/** The page header's actions element, for the parts of the page below it. */
export const PageActionsSlot = Slot.Provider;

/** Its children shown at the end of the page header's actions (nothing while the header is not drawn yet). */
export function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(Slot);
  return slot ? createPortal(children, slot) : null;
}
