// 231 (plan stage C, C3e; DECISIONS 231): the panels a domain adds under an item's to-dos in the review workspace (the
// finance domain's: the duplicate suspicions and the statement relations), each showing what the domain added to the
// item's result and nothing when there is none. The domain registers them when the interface loads (`ui/src/domains/`),
// so the review's field panel names none. Until C3e the field panel imported them.
import type { ComponentType } from "react";
import type { ItemResult } from "../api";

export interface ItemPanelProps { result: ItemResult; readOnly: boolean; onDecided: () => void }

const PANELS = new Map<string, ComponentType<ItemPanelProps>>();

/** Registers a domain's item panel by its name (a second registration replaces the first). */
export function registerItemPanel(name: string, Panel: ComponentType<ItemPanelProps>): void {
  PANELS.set(name, Panel);
}

/** The registered panels, in the order they registered. */
export function itemPanels(): [string, ComponentType<ItemPanelProps>][] {
  return [...PANELS.entries()];
}
