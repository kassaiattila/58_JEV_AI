// 176 (plan 170 L3) - 231 (C3b5a): the logic packs' registry on the interface went with the last logic pack (the
// statement package is a plain package of the statements rule; what its rule shows is `packageParts.tsx`). What is
// left here is the item parts of another domain.
import type { ReactNode } from "react";

/** 192 (plan F-quote-package B6a): how an item part another domain adds to an item's result is shown, by its name
 *  (`jav/app/item_kinds.py` item parts). 231 (C1a): none now; what an email may start is the general intake
 *  (`ui/src/elements/IntakeOffers.tsx`). */
export const ITEM_PARTS: Record<string, (value: unknown) => ReactNode> = {};
