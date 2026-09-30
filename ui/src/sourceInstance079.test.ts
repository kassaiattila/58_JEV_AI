// Source instances: the readiness codes and the review notice when the original file changed or disappeared since the
// document was added (with a kept copy the document is still shown; without one it cannot be).
import { describe, expect, it } from "vitest";
import { blockerText } from "./labels";
import { sourceFileNote } from "./views/ReviewWorkspace";

describe("source instances", () => {
  it("names the readiness codes in everyday words, with the file name", () => {
    expect(blockerText({ code: "instance_damaged", message: "The copy kept when it was added is missing or damaged: a.pdf" }))
      .toBe("A felvételkori példány hiányzik vagy sérült: a.pdf");
    expect(blockerText({ code: "original_changed", message: "The original file has changed since it was added; the copy kept then is processed: a.pdf" }))
      .toMatch(/megváltozott; a felvételkori példány kerül feldolgozásra: a\.pdf$/);
    expect(blockerText({ code: "original_missing", message: "The original file has disappeared since it was added; the copy kept then is processed: b.pdf" }))
      .toMatch(/eltűnt; .*: b\.pdf$/);
  });

  it("shows a notice only when the original is no longer what was added", () => {
    expect(sourceFileNote(undefined)).toBeNull();
    expect(sourceFileNote({ copy: true, original: "same" })).toBeNull();
    expect(sourceFileNote({ copy: true, original: "changed" })).toMatch(/felvételkori példány látható/);
    expect(sourceFileNote({ copy: true, original: "missing" })).toMatch(/eltűnt vagy nem olvasható/);
    expect(sourceFileNote({ copy: false, original: "changed" })).toMatch(/nem jeleníthető meg/);
  });
});
