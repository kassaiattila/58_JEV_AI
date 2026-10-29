// 261 (the consolidation round, DECISIONS 261): the review of an item of a kind a domain adds, by the item's kind, as
// the service's domains add their item kinds. The review workspace asks this registry instead of naming the kind (until
// 261 it chose the email domain's review by name); the domain registers its review when the interface loads
// (`ui/src/domains/<domain>/index.tsx`). A review that gives nothing for an item leaves it to the shared document review.
import type { ReactNode } from "react";
import type { ItemResult } from "../api";

export type ItemReviewProps = { data: ItemResult; wpId: string; onChanged: () => void };
export type ItemReview = (p: ItemReviewProps) => ReactNode;

const REVIEWS = new Map<string, ItemReview>();

/** Registers a domain's review of an item kind (a second registration replaces the first). */
export function registerItemReview(kind: string, review: ItemReview): void {
  REVIEWS.set(kind, review);
}

/** The review a domain registered for an item's kind (undefined: the shared document review). */
export function itemReviewOf(kind: string | undefined): ItemReview | undefined {
  return kind ? REVIEWS.get(kind) : undefined;
}
