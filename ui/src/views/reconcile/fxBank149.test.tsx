// 149: a forint bank line is compared with an invoice in another currency at the MNB rate of the invoice's fulfilment
// day or of the line's booking day; the pairing page names the day the amount matched at. A card line keeps its text.
import { describe, expect, it } from "vitest";
import type { ReconcileFx } from "../../api";
import { fxText } from "./labels";

const fx = (basis?: ReconcileFx["basis"]): ReconcileFx =>
  ({ rate: "368.16", rate_day: "2026-03-20", source: "mnb", converted: "368160.00", deviation: "0.0000", basis });

describe("the conversion of a pair (149)", () => {
  it("names the day whose MNB rate the amount matched at", () => {
    expect(fxText(fx("fulfillment"), "368 160 Ft")).toBe("368 160 Ft a teljesítés napi (2026-03-20) MNB-árfolyamon");
    expect(fxText(fx("booking"), "368 160 Ft")).toBe("368 160 Ft a könyvelés napi (2026-03-20) MNB-árfolyamon");
    expect(fxText(fx(), "368 160 Ft")).toBe("368 160 Ft a(z) 2026-03-20 napi MNB-árfolyamon"); // a card line, as before
  });
});
