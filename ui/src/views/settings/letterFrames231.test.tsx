// 231 (stage U, U3f; the owner's decision of 2026-10-28: the letter frames are edited now, with versions): the letter
// frames in the shared library. A frame shows its text field by field under its language, the processes that use it
// and its versions; a changed text is saved as a draft with only the fields that changed (paragraphs split at a blank
// line); a draft is made active with one button, and the own text is set aside after a confirmation. Invented data, a
// mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type LetterFrames } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { LetterFramesPanel } from "./LetterFramesPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const AT = "2026-10-28T09:00:00+00:00";
const FILE = { language: "en", subject: "Our offer - {{policyholder}}", greeting: "Dear {{contact_name}},", greeting_none: "Dear Sir or Madam,",
  paragraphs: ["Thank you for your request.", "The premium is {{total}}."], closing: "Kind regards,", file: "offer-letter" };
const LISTING = (versions: LetterFrames["kinds"][0]["frames"][0]["versions"], active: number | null = null): LetterFrames => ({
  policy: { activation: "editor", owners: [] },
  kinds: [{
    kind: "letter_frame", title: "Covering letters", what: "The letter that goes with a printed document.",
    markers: ["contact_name", "policyholder", "total"],
    fields: [{ path: "subject", label: "Subject", form: "line", group: null },
      { path: "greeting", label: "Greeting with the addressee's name", form: "line", group: null },
      { path: "paragraphs", label: "Paragraphs", form: "paragraphs", group: null },
      { path: "closing", label: "Closing", form: "line", group: null }],
    frames: [{ ident: "invented_letter", file: FILE, content: FILE, active, markers: ["policyholder", "contact_name", "total"], versions }],
  }],
});
const DRAFT = { version: 1, state: "draft" as const, content: { ...FILE, subject: "Offer - {{policyholder}}" }, note: "shorter",
  made_by: "Synthetic reviewer", made_at: AT, activated_by: null, activated_at: null };

describe("the letter frames (231 U3f)", () => {
  it("shows a frame's text field by field with the processes that use it", async () => {
    vi.spyOn(api, "letterFrames").mockResolvedValue(LISTING([]));
    vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: { invented_letter: [{ id: "invented_offer", title: "Invented offer" }] } });
    render(<LetterFramesPanel />);
    const frame = await screen.findByLabelText("invented_letter");
    expect(within(frame).getByText("the system's text")).toBeTruthy();
    expect(within(frame).getByText("Our offer - {{policyholder}}")).toBeTruthy();
    expect(within(frame).getByText("Thank you for your request.\n\nThe premium is {{total}}.", { normalizer: (s) => s })).toBeTruthy();
    expect((await within(frame).findByRole("link", { name: "Invented offer" })).closest(".used-by")?.textContent).toBe("Used by: Invented offer");
  });

  it("saves only the changed fields as a draft, the paragraphs split at a blank line", async () => {
    vi.spyOn(api, "letterFrames").mockResolvedValue(LISTING([]));
    vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: {} });
    const propose = vi.spyOn(api, "proposeLetterFrame").mockResolvedValue(LISTING([DRAFT]));
    render(<LetterFramesPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Change the text" }));
    const form = screen.getByRole("form", { name: "Change the text" });
    expect((within(form).getByRole("button", { name: "Save as a draft" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(form).getByLabelText("Subject"), { target: { value: "Offer - {{policyholder}}" } });
    fireEvent.change(within(form).getByLabelText(/Paragraphs/), { target: { value: "First.\n\n\nSecond, {{total}}.\n" } });
    fireEvent.change(within(form).getByLabelText("Note"), { target: { value: "shorter" } });
    expect(within(form).getByText("{{total}}")).toBeTruthy();  // the markers the kind's documents offer
    fireEvent.click(within(form).getByRole("button", { name: "Save as a draft" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith("letter_frame", "invented_letter",
      { subject: "Offer - {{policyholder}}", paragraphs: ["First.", "Second, {{total}}."] }, "shorter"));
    expect(await screen.findByText("Saved as a draft. Make it active to use it.")).toBeTruthy();
  });

  it("makes a draft active and sets the own text aside after a confirmation", async () => {
    vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: {} });
    const listing = vi.spyOn(api, "letterFrames").mockResolvedValue(LISTING([DRAFT]));
    const activate = vi.spyOn(api, "activateLetterFrame").mockResolvedValue(LISTING([{ ...DRAFT, state: "active" }], 1));
    render(<LetterFramesPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Make version 1 active" }));
    await waitFor(() => expect(activate).toHaveBeenCalledWith("letter_frame", "invented_letter", 1));
    listing.mockResolvedValue(LISTING([{ ...DRAFT, state: "active" }], 1));
    const retire = vi.spyOn(api, "retireLetterFrame").mockResolvedValue(LISTING([{ ...DRAFT, state: "retired" }]));
    const back = await screen.findByRole("button", { name: "Back to the system's text" });
    expect(screen.getByText("its own text: version 1")).toBeTruthy();
    fireEvent.click(back);
    expect(retire).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(retire).toHaveBeenCalledWith("letter_frame", "invented_letter"));
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Letter frames", "Covering letters", "Quote reply letters", "Change the text", "Back to the system's text",
      "the letter frame cannot be saved: {{problems}}"]) expect(hu[key]).toBeTruthy();
  });
});
