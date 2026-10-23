// 224 (plan G-process-core P3c): a version's state mark, one component for the price lists and the output templates
// (the service's shared versions). Each state has its own mark and label (the translation check covers the Hungarian).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { OutputTemplateState } from "../../api";
import { VersionState } from "../../components/VersionState";
import { setLanguage } from "../../i18n";

afterEach(() => { cleanup(); });

const STATES: [OutputTemplateState, string, string][] = [
  ["active", "s-done", "Active"],
  ["draft", "s-trial", "Draft"],
  ["superseded", "s-held", "Superseded"],
  ["retired", "s-removed", "Retired"],
];

describe("224 a version's state mark", () => {
  it("marks each state with its own class and label", async () => {
    await setLanguage("en");
    for (const [state, mark, label] of STATES) {
      render(<VersionState state={state} />);
      expect(screen.getByText(label).className).toBe(`status ${mark}`);
      cleanup();
    }
  });
});
