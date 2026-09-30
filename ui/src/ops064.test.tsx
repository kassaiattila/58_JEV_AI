// 064 (decision of 2026-09-29): the store backup's status on the System page — OK, failed, too old, or the copy to the
// second location failed; a failure does not stay silent. „Mentés most” (Back up now) uses the daily backup's settings.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type BackupInfo } from "./api";
import { BackupPanel, backupState, docsLine } from "./views/settings/BackupPanel";

afterEach(() => vi.restoreAllMocks());

const CONFIG = { schedule: "12:00", keep: 14, copy_to: "\\\\nas\\mentes", with_burr: false, max_age_hours: 36 };
const NOW = new Date("2026-09-30T12:30:00");
const ok = (created_at: string, copyOk = true): BackupInfo => ({
  config: CONFIG,
  status: { created_at, ok: true, dir: "store\\backups\\20260930-120000", files: [{ file: "jav.sqlite", bytes: 39_300_000, integrity: "ok" }],
    copy: { dir: "\\\\nas\\mentes\\20260930-120000", ok: copyOk, verified: copyOk, error: copyOk ? undefined : "OSError: a hálózati hely nem érhető el" } },
});

describe("064 adattár-mentés", () => {
  it("az állapot szintje: rendben, túl régi, sikertelen másolat, hiba, még nincs", () => {
    expect(backupState(ok("2026-09-30T12:00:00"), NOW).level).toBe("ok");
    const stale = backupState(ok("2026-09-28T12:00:00"), NOW);
    expect(stale.level).toBe("warn");
    expect(stale.text).toMatch(/48 órája/);
    expect(backupState(ok("2026-09-30T12:00:00", false), NOW).text).toMatch(/másolat a második helyre nem sikerült/);
    expect(backupState({ config: CONFIG, status: { created_at: "2026-09-30T12:00:00", ok: false, error: "ValueError: no store" } }, NOW).level).toBe("error");
    expect(backupState({ config: CONFIG, status: null }, NOW).text).toBe("Még nem készült mentés.");
  });

  it("070: a belső dokumentumok sora — a mentésben, hiányzik, vagy ki van kapcsolva", () => {
    const withDocs = ok("2026-09-30T12:00:00");
    withDocs.status!.files!.push({ file: "internal-docs.zip", bytes: 420_000, integrity: "ok", entries: 154 });
    expect(docsLine(withDocs)).toBe("154 fájl (0.4 MB)");
    expect(docsLine({ ...ok("2026-09-30T12:00:00"), config: { ...CONFIG, with_docs: true } })).toBe("nincs a legutóbbi mentésben");
    expect(docsLine(ok("2026-09-30T12:00:00"))).toBe("kikapcsolva");
  });

  it("a Mentés most a napi beállítással ment, és frissíti az állapotot", async () => {
    const status = vi.spyOn(api, "backupStatus").mockResolvedValue(ok(new Date().toISOString()));
    const now = vi.spyOn(api, "backupNow").mockResolvedValue({ created_at: new Date().toISOString(), ok: true, dir: "store\\backups\\uj", copy: null });
    render(<BackupPanel />);
    expect(await screen.findByText(/^Legutóbbi mentés:/)).toBeTruthy();
    expect(screen.getByText(/Napi mentés 12:00-kor/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Mentés most" }));
    expect(now).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Mentés kész: store\\backups\\uj")).toBeTruthy();
    await waitFor(() => expect(status.mock.calls.length).toBeGreaterThanOrEqual(2)); // the status reloads after the backup
  });
});
