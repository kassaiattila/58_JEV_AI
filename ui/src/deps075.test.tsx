// 075: the dependency audit card on the System page — the state sentence and its level, and
// the card drawn from the service's answer.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DepsAuditInfo } from "./api";
import { DepsAuditPanel, depsAuditState } from "./views/settings/DepsAuditPanel";

afterEach(() => vi.restoreAllMocks());

const info = (over: Partial<NonNullable<DepsAuditInfo["status"]>> = {}): DepsAuditInfo => ({
  status: {
    checked_at: "2026-09-30T10:56:39+00:00", age_days: 0, stale: false, finding_count: 0, errors: [],
    python: { packages: 69 }, npm: { packages: 137 }, ...over,
  },
  max_age_days: 7,
});

describe("075 dependency audit on the System page", () => {
  it("names the level and the package counts", () => {
    expect(depsAuditState(info())).toMatchObject({ level: "ok" });
    expect(depsAuditState(info()).text).toMatch(/69 Python- és 137 felület-csomag/);
    expect(depsAuditState(info({ finding_count: 2 }))).toMatchObject({ level: "error" });
    expect(depsAuditState(info({ stale: true, age_days: 9 })).text).toMatch(/7 napnál régebbi/);
    expect(depsAuditState(info({ errors: ["python: pip-audit not found"] })).text).toMatch(/nem teljes.*pip-audit not found/);
    expect(depsAuditState({ status: null, max_age_days: 7 })).toMatchObject({ level: "warn" });
  });

  it("draws the card from the service's answer", async () => {
    vi.spyOn(api, "depsAudit").mockResolvedValue(info({ finding_count: 1 }));
    render(<DepsAuditPanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/1 ismert sebezhetőség/);
    expect(screen.getByText("python -m jav.cli deps-audit")).toBeTruthy();
  });
});
