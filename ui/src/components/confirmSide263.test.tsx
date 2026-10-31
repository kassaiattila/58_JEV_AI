// 263 (plan E, F4): a confirmation card stays beside its button - a button at a form's left foot opened its card
// leftwards, over the side panel. Synthetic layout.
import { describe, expect, it } from "vitest";
import { cardSide } from "./ConfirmButton";

describe("the side a confirmation card opens to", () => {
  it("is the button's left edge for a button in the left half of the window", () => {
    expect(cardSide({ left: 308, width: 72 }, 1366)).toBe("left");
  });

  it("is the button's right edge for a button in the right half of the window", () => {
    expect(cardSide({ left: 1180, width: 140 }, 1366)).toBe("right");
  });
});
