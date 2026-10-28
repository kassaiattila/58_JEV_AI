// 231 (stage U, U1; the walkthrough of 2026-10-28): a view whose key changes never renders the old key's data. Going
// from a reconciliation case to a mailbox case, the case page rendered once with the reconciliation's view under the
// mailbox case's id, and its pairing element asked the service for the mailbox case's reconciliation (422). The load
// hook gives no data for a key it has not loaded yet. No service.
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useLoad } from "./hooks";

describe("a load under a new key (231 U1)", () => {
  it("shows no data of the key before until the new key's answer arrives", async () => {
    const answers: Record<string, (v: string) => void> = {};
    const seen: [string, string | null][] = [];
    const { rerender } = renderHook(({ key }) => {
      const loaded = useLoad(key, () => new Promise<string>((resolve) => { answers[key] = resolve; }));
      seen.push([key, loaded.data]);
      return loaded;
    }, { initialProps: { key: "case-a" } });
    await act(async () => { answers["case-a"]("view of a"); });
    rerender({ key: "case-b" });
    expect(seen.filter(([key, data]) => key === "case-b" && data === "view of a")).toEqual([]);
    await act(async () => { answers["case-b"]("view of b"); });
    expect(seen.at(-1)).toEqual(["case-b", "view of b"]);
  });
});
