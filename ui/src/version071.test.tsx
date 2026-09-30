// 071 S-verzió (audit A08 / §1): a Rendszer oldalon látszik, melyik kód fut — verzió, commit, és figyelmeztetés, ha a
// futó kód commitolatlan változást tartalmaz vagy a commit nem ismert.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Health } from "./api";
import { VersionPanel, versionLine, versionWarning } from "./views/settings/VersionPanel";

afterEach(() => vi.restoreAllMocks());

const health = (over: Partial<Health> = {}): Health => ({
  ok: true, api_version: "1", service_config: "1.6.0", version: "1.0.5", commit: "abc1234", dirty: false,
  started_at: "2026-09-30T10:00:00+00:00", ...over,
});

describe("071 verzió a Rendszer oldalon", () => {
  it("a sor: verzió és commit; commit nélkül csak a verzió", () => {
    expect(versionLine(health())).toBe("v1.0.5 · commit abc1234");
    expect(versionLine(health({ commit: null, dirty: null }))).toBe("v1.0.5");
  });

  it("figyelmeztet a commitolatlan változásra és az ismeretlen commitra", () => {
    expect(versionWarning(health())).toBeNull();
    expect(versionWarning(health({ dirty: true }))).toMatch(/commitolatlan/);
    expect(versionWarning(health({ commit: null, dirty: null }))).toMatch(/nem ismert/);
  });

  it("a kártya a szolgáltatás válaszából rajzol", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health({ dirty: true }));
    render(<VersionPanel />);
    expect(await screen.findByText("v1.0.5 · commit abc1234")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/commitolatlan/);
    expect(screen.getByText(/óta fut/)).toBeTruthy();
  });
});
