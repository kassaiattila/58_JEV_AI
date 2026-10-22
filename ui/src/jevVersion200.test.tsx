// 200 (the owner's decision of 2026-10-22): the JEV version card on the System page — the system asks a pinned JEV
// version; the daily backup looks where the provider's moving name points, and the card says when a newer version is out
// (a notice: switching is a decision with a measurement). Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type JevVersionInfo } from "./api";
import { setLanguage } from "./i18n";
import { JevVersionPanel, jevVersionState } from "./views/settings/JevVersionPanel";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const info = (over: Partial<JevVersionInfo> = {}): JevVersionInfo => ({
  pinned: "jev-1.14.0", watch_alias: "jev-latest", latest: "jev-1.14.0", checked_at: "2026-10-22T10:00:00+00:00",
  newer: false, stale: false, age_days: 0.1, ...over,
});

describe("200 the pinned JEV version on the System page", () => {
  it("says the pinned version is the latest", () => {
    expect(jevVersionState(info())).toMatchObject({ level: "ok" });
    expect(jevVersionState(info()).text).toMatch(/jev-1\.14\.0 változatot kérdezi; ez a legújabb is/);
  });

  it("reports a newer version without taking it", () => {
    const state = jevVersionState(info({ latest: "jev-1.15.0", newer: true }));
    expect(state.level).toBe("warn");
    expect(state.text).toMatch(/Újabb JEV-változat érhető el: jev-1\.15\.0.*továbbra is a jev-1\.14\.0.*döntés és mérés/);
  });

  it("says when there has been no look, or an old one, or the model is not pinned", () => {
    expect(jevVersionState(info({ latest: null, checked_at: null, newer: null, age_days: null }))).toMatchObject({ level: "warn" });
    expect(jevVersionState(info({ stale: true, age_days: 4.2 })).text).toMatch(/4 napja/);
    expect(jevVersionState(info({ pinned: "jev-latest", newer: null })).text).toMatch(/nincs rögzítve/);
  });

  it("draws the card from the service's answer, in English too", async () => {
    vi.spyOn(api, "jevVersion").mockResolvedValue(info({ latest: "jev-1.15.0", newer: true }));
    await setLanguage("en");
    render(<JevVersionPanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/A newer JEV version is out: jev-1\.15\.0/);
  });
});
