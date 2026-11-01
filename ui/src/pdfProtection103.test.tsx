import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type Health, type PdfProtection } from "./api";
import { setLanguage } from "./i18n";
import { PdfProtectionPanel } from "./views/settings/PdfProtectionPanel";
import hungarian from "./i18n/hu-native.json";

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
const hu = hungarian as Record<string, string>;
const PANEL = ["PDF memory protection", "Service", "Worker", "Protected", "Memory limit unavailable", "Unknown", "Stale", "Configured limit", "Effective limit", "Strict mode", "On", "Off", "Not established", "The reader has not started yet.", "The helper has stopped.", "Windows could not apply the memory limit.", "Isolation is disabled.", "The memory limit is disabled.", "The operating system applied the memory limit.", "The worker is not running.", "The worker instance has ended.", "The report has expired.", "No current report is available.", "The report cannot be verified.", "Settings changed after the helper started.", "The helper is starting.", "The memory limit could not be established.", "The status request failed.", "Strict mode refuses PDF reading without a memory limit. It is off by default."];

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
  expect(screen.getByRole("region", { name: hu["PDF memory protection"] })).toBeTruthy();
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
  // 265 (code review UI-03): in the shared Hungarian dictionary (until then the panel's own)
  for (const source of PANEL) {
    expect(hu[source]?.trim(), source).toBeTruthy();
    expect(hu[source]).not.toBe(source);
  }
});
