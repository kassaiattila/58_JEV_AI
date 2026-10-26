// 231 (plan stage C, C3e; DECISIONS 231): the quotes domain's screens on the interface, registered when it loads, as the
// service's quotes domain registers its addresses and capabilities (`jav/domains/quotes/__init__.py`): its calls on the
// shared client, the quote's capabilities' elements of a case's tabs (the request, the proposal, the draft's lines and
// the approval), and Settings › Price lists. The pages load on first use; only the quote's status lines
// (`./quoteStatus.ts`) load with the interface.
import { lazy } from "react";
import { registerCalls } from "../../api";
import { lazyPage } from "../../components/LazyPage";
import { lazily, registerApprovalBody, registerElement, type ElementProps } from "../../elements/registry";
import { registerSettingsSection } from "../../logic/settingsSections";
import { quotesApi, type QuoteView } from "./api";
import { quoteStatus, quoteSummary } from "./quoteStatus";

registerCalls(quotesApi);

// the quote's capabilities' elements: their pages load only when a case shows one; their status lines and summary are
// the quote package's (quoteStatus.ts), from the quote view their data carries
const quote = () => import("./QuoteElements");
const RecordView = lazy(() => quote().then((m) => ({ default: m.RecordView })));
const MatchProposal = lazy(() => quote().then((m) => ({ default: m.MatchProposal })));
const LineEditor = lazy(() => quote().then((m) => ({ default: m.LineEditor })));
const Approval = lazy(() => quote().then((m) => ({ default: m.Approval })));
const quoteOf = (p: ElementProps) => (p.element.data as { quote?: QuoteView } | null)?.quote;
const quoteLine = (which: "process" | "review" | "result") => (p: ElementProps) => quoteStatus(quoteOf(p))?.[which] ?? null;

registerElement("record_view", { render: lazily(RecordView), status: quoteLine("process"), summary: (p) => quoteSummary(quoteOf(p)) });
registerElement("match_proposal", { render: lazily(MatchProposal), status: quoteLine("review") });
registerElement("line_editor", { render: lazily(LineEditor), status: quoteLine("review") });
// D0-d: the shared approval element shows the quote's own approval for its line composition steps
registerApprovalBody("line_draft", { render: lazily(Approval), status: quoteLine("result") });

// 191 (plan F-quote-package B2): the seller's price lists a quote is priced from
registerSettingsSection({
  key: "prices", label: "Price lists", hint: "The price lists quotes are priced from: upload, check and make active; the volume discounts, the currency and the VAT rate",
  order: 90, Panel: lazyPage(() => import("./PriceListsPanel").then((m) => m.PriceListsPanel)),
});
