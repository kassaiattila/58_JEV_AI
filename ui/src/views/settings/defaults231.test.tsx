// 231 (stage U, U4d; the owner's decisions of 2026-10-29): a rule value's default on the rule's sheet (Settings ›
// Defaults). A value says whether the file's or the installation's own value counts; its form fits its kind (a
// percentage edited as one, the email's routes per intent), is tried on the earlier decisions and saved as a draft;
// a draft is made active, and the own value set aside after a confirmation; a value that costs money says why it
// stays the file's. Invented data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DefaultKey, type Defaults, type DefaultPreview } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { DefaultEditor } from "./DefaultEditor";
import type { RuleValue } from "./RulesPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-29T09:00:00+00:00";
const BAND: RuleValue = { file: "policy.json", key: "bands.default.choice_human_max_conf", label: "A person decides below", format: "percent", value: 0.6 };
const BAND_KEY: DefaultKey = {
  id: "policy.bands.default.choice_human_max_conf", file: "policy", key: "bands.default.choice_human_max_conf", kind: "number",
  what: "A person decides below", least: 0, most: 1, options: [], file_value: 0.6, value: null, active: null, versions: [],
};
const DONE: Defaults = { keys: [], fixed: {}, policy: { activation: "editor", owners: [] } };
const TRIED: DefaultPreview = { id: BAND_KEY.id, value: 0.7, file_value: 0.6, decisions: 12, changed: 2, failed: 0, covered: 1,
  first_error: null, examples: [{ point: "extract.route", subject: "item:it-1", case_id: null, case: null, at: AT, before: "accept", after: "review" }] };

describe("a rule value's default (231 U4d)", () => {
  it("edits a percentage as one, tries it on the earlier decisions and saves it as a draft", async () => {
    const preview = vi.spyOn(api, "previewDefault").mockResolvedValue(TRIED);
    const propose = vi.spyOn(api, "proposeDefault").mockResolvedValue(DONE);
    const changed = vi.fn();
    render(<DefaultEditor v={BAND} entry={BAND_KEY} fixed={undefined} onChanged={changed} />);
    expect(screen.getByText("The file's value counts.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Set a default" }));
    const form = screen.getByRole("form", { name: "Set a default" });
    const input = within(form).getByLabelText(/A person decides below/) as HTMLInputElement;
    expect(input.value).toBe("60");
    fireEvent.change(input, { target: { value: "70" } });
    fireEvent.click(within(form).getByRole("button", { name: "Try it on earlier decisions" }));
    await waitFor(() => expect(preview).toHaveBeenCalledWith(BAND_KEY.id, 0.7));
    expect((await within(form).findByRole("status")).textContent).toContain("12 earlier decisions read it: 2 would come out differently");
    expect(within(form).getByText(/1 more were decided by a process's own value/)).toBeTruthy();
    fireEvent.change(within(form).getByLabelText("Note"), { target: { value: "fewer to-dos" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save as a draft" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith(BAND_KEY.id, 0.7, "fewer to-dos"));
    expect(changed).toHaveBeenCalled();
  });

  it("chooses each intent's route from the routes the rules name", async () => {
    const routes: RuleValue = { file: "email.json", key: "intent_route", label: "Each intent's next step", format: "routes", value: [] };
    const entry: DefaultKey = { ...BAND_KEY, id: "email.intent_route", file: "email", key: "intent_route", kind: "map", least: null, most: null,
      what: "Each intent's next step", options: ["human:inbox", "m2:quote_request"], file_value: { quote_request: "m2:quote_request" } };
    const propose = vi.spyOn(api, "proposeDefault").mockResolvedValue(DONE);
    render(<DefaultEditor v={routes} entry={entry} fixed={undefined} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Set a default" }));
    const form = screen.getByRole("form", { name: "Set a default" });
    fireEvent.change(within(form).getByLabelText("quote_request"), { target: { value: "human:inbox" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save as a draft" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith("email.intent_route", { quote_request: "human:inbox" }, null));
  });

  it("edits an ordered list of codes one a line (U4z: the catalogue's levels)", async () => {
    const levels: RuleValue = { file: "facts_property.json", key: "levels", label: "The levels of the units", format: "names", value: [] };
    const entry: DefaultKey = { ...BAND_KEY, id: "facts_property.levels", file: "facts_property", key: "levels", kind: "list", least: 1,
      most: null, what: "The levels of the units", options: [], file_value: ["holder", "site", "asset_group"] };
    const propose = vi.spyOn(api, "proposeDefault").mockResolvedValue(DONE);
    render(<DefaultEditor v={levels} entry={entry} fixed={undefined} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Set a default" }));
    const form = screen.getByRole("form", { name: "Set a default" });
    const box = within(form).getByLabelText(/The levels of the units/) as HTMLTextAreaElement;
    expect(box.value).toBe(["holder", "site", "asset_group"].join(String.fromCharCode(10)));
    fireEvent.change(box, { target: { value: [" holder", "", "asset_group "].join(String.fromCharCode(10)) } });
    fireEvent.click(within(form).getByRole("button", { name: "Save as a draft" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith("facts_property.levels", ["holder", "asset_group"], null));
  });

  it("makes a draft active and sets the own value aside after a confirmation", async () => {
    const versions = [{ version: 1, state: "draft" as const, value: 0.7, note: null, made_by: "Synthetic reviewer", made_at: AT,
      activated_by: null, activated_at: null }];
    const activate = vi.spyOn(api, "activateDefault").mockResolvedValue(DONE);
    const { rerender } = render(<DefaultEditor v={BAND} entry={{ ...BAND_KEY, versions }} fixed={undefined} onChanged={vi.fn()} />);
    expect(screen.getByRole("row", { name: /version 1/ }).textContent).toContain("70");
    fireEvent.click(screen.getByRole("button", { name: "Make version 1 active" }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith(BAND_KEY.id, 1));
    const retire = vi.spyOn(api, "retireDefault").mockResolvedValue(DONE);
    rerender(<DefaultEditor v={BAND} entry={{ ...BAND_KEY, value: 0.7, active: 1, versions: [{ ...versions[0], state: "active" }] }}
      fixed={undefined} onChanged={vi.fn()} />);
    expect(screen.getByText(/The installation's own value: version 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back to the file's value" }));
    expect(retire).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(retire).toHaveBeenCalledWith(BAND_KEY.id));
  });

  it("says why a value that costs money stays the file's", () => {
    render(<DefaultEditor v={BAND} entry={undefined} fixed="cost" onChanged={vi.fn()} />);
    expect(screen.getByText("Stays the file's value: it changes a paid request or a budget.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Set a default" })).toBeNull();
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Defaults", "Set a default", "Back to the file's value", "The file's value counts.",
      "Stays the file's value: it changes a paid request or a budget."]) expect(hu[key]).toBeTruthy();
  });
});
