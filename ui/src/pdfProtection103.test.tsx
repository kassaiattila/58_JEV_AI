import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type Health, type PdfProtection } from "./api";
import { setLanguage } from "./i18n";
import { PdfProtectionPanel } from "./views/settings/PdfProtectionPanel";
import hu from "./i18n/hu-pdf-protection.json";

const report = (state: PdfProtection["state"], reason: string): PdfProtection => ({
  state, reason, configured: { isolated: true, memory_mb: 512, require_memory_limit: false },
  effective_memory_mb: state === "protected" ? 512 : null, helper_pid: 123, process_pid: 100,
  observed_at: Date.now() / 1000,
});
const health = (service: PdfProtection, worker: PdfProtection): Health => ({
  ok: true, api_version: "1", service_config: "1.9.1", version: "1.6.0", commit: "abc1234", dirty: false,
  started_at: new Date().toISOString(), pdf_protection: { service, worker },
});

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); await setLanguage("hu"); });

it("separates a protected service from an unprotected worker and shows configured versus effective limits", async () => {
  vi.spyOn(api, "health").mockResolvedValue(health(report("protected", "memory_limit_applied"), report("unprotected", "windows_job_unavailable")));
  render(<PdfProtectionPanel />);
  const service = screen.getByRole("group", { name: "Service" });
  const worker = screen.getByRole("group", { name: "Worker" });
  expect(await within(service).findByText("Protected")).toBeTruthy();
  expect(within(worker).getByText("Memory limit unavailable")).toBeTruthy();
  expect(worker.textContent).toContain("Effective limit: Not established");
  expect(service.textContent).toContain("Effective limit: 512 MB");
  expect(service.textContent).toContain("Strict mode: Off");
  await act(() => setLanguage("hu"));
  expect(screen.getByRole("group", { name: hu.Worker }).textContent).toContain(hu["Memory limit unavailable"]);
});

it("keeps legacy or missing reports unknown", async () => {
  const old = health(report("protected", "memory_limit_applied"), report("protected", "memory_limit_applied"));
  delete old.pdf_protection;
  vi.spyOn(api, "health").mockResolvedValue(old);
  render(<PdfProtectionPanel />);
  await waitFor(() => expect(api.health).toHaveBeenCalled());
  expect(screen.queryByText("Protected")).toBeNull();
  expect(screen.getAllByText("Unknown")).toHaveLength(2);
});

it("expires a formerly green report even when a refresh remains pending", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "health").mockResolvedValueOnce(health(report("protected", "memory_limit_applied"), report("unknown", "not_started")))
    .mockImplementation(() => new Promise(() => {}));
  render(<PdfProtectionPanel />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText("Protected")).toBeTruthy();
  await act(async () => { vi.advanceTimersByTime(12000); });
  expect(screen.queryByText("Protected")).toBeNull();
  expect(screen.getAllByText("Stale")).toHaveLength(2);
});

it("a failed refresh invalidates a green observation immediately", async () => {
  vi.useFakeTimers();
  vi.spyOn(api, "health").mockResolvedValueOnce(health(report("protected", "memory_limit_applied"), report("unknown", "not_started")))
    .mockRejectedValue(new Error("offline"));
  render(<PdfProtectionPanel />);
  await act(async () => { await Promise.resolve(); });
  await act(async () => { vi.advanceTimersByTime(2100); });
  expect(screen.queryByText("Protected")).toBeNull();
  expect(screen.getAllByText("The status request failed.")).toHaveLength(2);
});

it("contains a non-empty Hungarian translation for every panel message", () => {
  for (const [source, translated] of Object.entries(hu)) {
    expect(source.trim()).toBeTruthy();
    expect(translated.trim()).toBeTruthy();
    expect(translated).not.toBe(source);
  }
});
