// 183 (backlog N-angol-felulet-maradek): the warning mark of an uncertain unified name says why in the interface's
// language, from the reasons' codes; without codes (an older answer) it shows the service's text as before.
// Artificial data, no service.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { NameWarning, nameCheckText } from "./components/NameCell";
import { setLanguage } from "./i18n";
import { fieldLabel } from "./labels";

afterEach(async () => { cleanup(); await setLanguage("hu"); });

it("writes the reasons in the interface's language", async () => {
  await setLanguage("en");
  expect(nameCheckText(["missing:invoice_number", "type", "todo:*", "odd:code"]))
    .toBe(`missing: ${fieldLabel("invoice_number")}; the type is unknown or uncertain; an open to-do about the whole document; odd:code`);
  render(<NameWarning check="hianyzik: Szamla sorszama" reasons={["todo:issue_date"]} />);
  expect(screen.getByLabelText(`Name to check: open to-do: ${fieldLabel("issue_date")}`)).toBeTruthy();
  await setLanguage("hu");
  expect(nameCheckText(["missing:invoice_number"])).toBe(`hi\u00e1nyzik: ${fieldLabel("invoice_number")}`);
});

it("without codes it shows the service's text", async () => {
  await setLanguage("en");
  render(<NameWarning check="hianyzik: Szamla sorszama" />);
  expect(screen.getByLabelText("Name to check: hianyzik: Szamla sorszama")).toBeTruthy();
});
