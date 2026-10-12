// 149: a message read from the Sent Items folder is not asked about its intent (the question reads the sender's aim).
// Its review page says so instead of "could not be detected", and its suggested next step has a name.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ItemResult } from "../api";
import { nextFlowText } from "../labels";
import { EmailReview } from "./EmailReview";

const mail = (sent: boolean): ItemResult => ({
  run_id: "run-000000000001", item_id: "a".repeat(64), kind: "email", extraction: null, source: null, provenance: {},
  open_reasons: [{ id: 1, reason: "attachment:unreadable:timeout", producer: "email_intent", run_id: "run-000000000001" }],
  email: { subject: "Invoice INV-0001", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "",
    attachments: [], result: { intent: null, intent_label: null, confidence: null, next_flow: "archive:sent", attachments: [],
      from_this_run: true, signals: {}, sent } },
} as unknown as ItemResult);

describe("a sent message (149)", () => {
  it("says its intent is not asked, not that it could not be recognised", () => {
    const { unmount } = render(<EmailReview data={mail(true)} onChanged={() => {}} />);
    expect(screen.getByText("Elküldött levél: a szándékát nem kérdezzük")).toBeTruthy();
    expect(screen.queryByText("nem sikerült felismerni")).toBeNull();
    unmount();
    render(<EmailReview data={mail(false)} onChanged={() => {}} />);
    expect(screen.getByText("nem sikerült felismerni")).toBeTruthy(); // an Inbox message without an intent is unchanged
  });

  it("names the archive route of a sent message", () => {
    expect(nextFlowText("archive:sent")).toBe("Archiválás (elküldött levél)");
  });
});
