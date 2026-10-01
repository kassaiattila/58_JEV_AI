// 083 (the owner's report of 2026-10-01): a value printed over several lines (an address) was unreadable on the image:
// each line got its own thick frame with a white ring, drawn over the neighbouring lines, and the other candidates'
// dashed boxes and their tags covered the same text. Now the lines are highlighted together, like a marker (a
// see-through fill per line), inside one thin common frame drawn outside the text; a candidate box that lies within the
// value has no border of its own, and its tag sits beside it. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Provenance } from "./api";
import { insideShare, unionBox } from "./review/geometry";
import { PageViewer } from "./review/PageViewer";

const LINES: [number, number, number, number][] = [[0.10, 0.10, 0.30, 0.12], [0.10, 0.125, 0.26, 0.145], [0.10, 0.15, 0.18, 0.17]];

function viewer(prov: Record<string, Provenance>) {
  const out = render(<PageViewer pageUrl={() => "/p/1.png"} pages={[{ page: 1, width_pt: 600, height_pt: 800 }]} prov={prov}
    activeField="supplier_address" focusRequest={0} colorOf={() => "#0057FF"} labelOf={(f) => f} onPickField={() => {}}
    onChooseAlternative={() => {}} selectMode words={null} selected={[]} onSelect={() => {}} />);
  fireEvent.load(screen.getByAltText("Az irat 1. oldala"));
  return out.container;
}

describe("083 a value over several lines", () => {
  it("the box around all lines and the share of a box inside another", () => {
    expect(unionBox(LINES)).toEqual([0.10, 0.10, 0.30, 0.17]);
    expect(insideShare([0.10, 0.10, 0.20, 0.12], [0.10, 0.10, 0.30, 0.17])).toBeCloseTo(1);
    expect(insideShare([0.25, 0.15, 0.35, 0.17], [0.10, 0.10, 0.30, 0.17])).toBeCloseTo(0.5);
    expect(insideShare([0.5, 0.5, 0.6, 0.6], [0.10, 0.10, 0.30, 0.17])).toBe(0);
  });

  it("is highlighted line by line, inside one common frame around the whole value", () => {
    const box = viewer({ supplier_address: { status: "located", method: "pick", alternatives: [], page: 1, bbox: [0.10, 0.10, 0.30, 0.17], boxes: LINES } });
    expect(box.querySelectorAll(".field-mark")).toHaveLength(3);
    const frames = box.querySelectorAll(".field-box.active");
    expect(frames).toHaveLength(1);
    const frame = frames[0] as HTMLElement;
    // the common frame encloses every line (with a small margin outside the text)
    expect(parseFloat(frame.style.left)).toBeLessThanOrEqual(10);
    expect(parseFloat(frame.style.top)).toBeLessThanOrEqual(10);
    expect(parseFloat(frame.style.left) + parseFloat(frame.style.width)).toBeGreaterThanOrEqual(30);
    expect(parseFloat(frame.style.top) + parseFloat(frame.style.height)).toBeGreaterThanOrEqual(17);
  });

  it("a candidate inside the value has no border of its own; one elsewhere keeps its dashed box; both keep their tag", () => {
    const box = viewer({ supplier_address: { status: "located", method: "pick", page: 1, bbox: [0.10, 0.10, 0.30, 0.17], boxes: LINES,
      alternatives: [{ value: "P.O Box 12720 AN", p: 0.02, page: 1, bbox: [0.10, 0.10, 0.25, 0.12] },
        { value: "Elsewhere", p: 0.31, page: 1, bbox: [0.6, 0.6, 0.8, 0.62] }] } });
    const alts = [...box.querySelectorAll(".alt-box")];
    expect(alts.map((a) => a.classList.contains("alt-inside"))).toEqual([true, false]);
    expect(screen.getByRole("button", { name: "2%" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "31%" })).toBeTruthy();
  });
});
