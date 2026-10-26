// 231 (stage D0, D0-a; the reassessment of 2026-10-26, F06): the interface's screen element components match the
// catalogue (configs/screen_elements.json). A built element has its component (a shared one, or one its domain registers
// when the interface loads); a planned one has none yet, and no pack may use it (the pack check). A case page that
// still meets an element it cannot show says so instead of leaving its tab empty. Synthetic data, a mocked service.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import catalogue from "../../../configs/screen_elements.json";
import { api, type CaseView } from "../api";
import { setLanguage } from "../i18n";
import { CasePage } from "../views/CasePage";
import { elementOf } from "./registry";

const elements = catalogue.elements as Record<string, { kind: string; status?: string }>;
const names = (planned: boolean) => Object.keys(elements).filter((k) => (elements[k].status === "planned") === planned).sort();

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => { vi.restoreAllMocks(); });

describe("the screen element catalogue", () => {
  it("has a component for every built element", () => {
    expect(names(false).filter((k) => !elementOf(k))).toEqual([]);
  });

  it("has none for a planned element yet", () => {
    expect(names(true)).toEqual(["actions", "blockers", "data_table", "form"]);  // D-f4: the field review is built; D-f7: the document view
    expect(names(true).filter((k) => elementOf(k))).toEqual([]);
  });

  it("says on a case's page that an element cannot be shown", async () => {
    const page: CaseView = {
      case: { id: "wp-000000000d0a", pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case", status: "open" },
      steps: {},
      tabs: [{ id: "only", label: "Only", elements: [{ type: "gauge", step: null, data: null }] }],
      next: null,
    };
    vi.spyOn(api, "casePage").mockResolvedValue(page);
    vi.spyOn(api, "workpackage").mockRejectedValue(new Error("no package in this test"));
    render(<CasePage caseId="wp-000000000d0a" tab="only" />);
    expect((await screen.findByRole("alert")).textContent).toBe("This screen element cannot be shown: gauge");
  });
});
