// 153 (review): the approval's blockers are grouped by reason; a group of several opens to list its documents. The
// card chips say they count cards. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ReconcileBlocker } from "../../api";
import { BlockerList } from "./BlockerList";

const blocker = (n: number, code = "source_not_approved"): ReconcileBlocker =>
  ({ code, doc_id: `doc-${String(n).padStart(12, "0")}`, file: `invoice-${n}.pdf`, kind: "invoice" }) as ReconcileBlocker;

describe("153 the approval's blockers", () => {
  it("are one line per reason, with the documents behind it", () => {
    const { container } = render(<BlockerList blockers={[...Array.from({ length: 355 }, (_, i) => blocker(i)), blocker(999, "source_no_run")]} />);
    expect(screen.getByText("355 irat még jóvá nem hagyott futásból származik")).toBeTruthy();
    expect(container.querySelectorAll("details")).toHaveLength(1); // the single command-line document stands alone
    expect(screen.getByText(/invoice-999\.pdf/)).toBeTruthy();
    expect(container.querySelectorAll("details li")).toHaveLength(355);
  });
});
