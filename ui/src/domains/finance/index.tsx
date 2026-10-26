// 231 (plan stage C, C3e; DECISIONS 231): the finance domain's screens on the interface, registered when it loads, as the
// service's finance domain registers its addresses, rules and capabilities (`jav/domains/finance/__init__.py`): its
// calls on the shared client; the statements rule's package part (its summary, its result panel, its own way of adding
// and its own scope); the review's duplicate and statement panels; the utility cost's view of the Result section; the
// pairing's elements of a case's tabs; Settings › Own parties and the bank files under Settings › Processing. The
// pages a person opens rarely load on first use.
import { lazy } from "react";
import { registerCalls } from "../../api";
import { lazyPage } from "../../components/LazyPage";
import { lazily, registerElement } from "../../elements/registry";
import { t } from "../../i18n";
import { registerPackagePart } from "../../logic/packageParts";
import { registerResultTable } from "../../logic/resultTables";
import { registerSettingsPart, registerSettingsSection } from "../../logic/settingsSections";
import { registerItemPanel } from "../../review/itemPanels";
import { AddStatements } from "./AddStatements";
import { financeApi } from "./api";
import { DuplicatePanel } from "./DuplicatePanel";
import { pairingLine, pairingSummary } from "./pairingStatus";
import { StatementPanel } from "./StatementPanel";
import { UtilityPanel } from "./UtilityReport";

registerCalls(financeApi);

// 140: a statement package's party, period and statements, and the party's months before and after its run
const StatementPackagePanel = lazyPage(() => import("./StatementPackagePanel").then((m) => m.StatementPackagePanel));
registerPackagePart("statements", {
  createdFrom: () => t("a statement package"),
  summary: (view) => (view.statements
    ? `${t("Bank statements of {{party}}, {{from}} – {{to}}", { party: view.statements.scope.party.name, from: view.statements.scope.period_start, to: view.statements.scope.period_end })} · `
    : null),
  resultPanel: (view) => (view.statements ? <StatementPackagePanel view={view.statements} /> : null),
  addLabel: "Add statements",
  Add: AddStatements,
  ownScope: true,
});

// 126: a document's duplicate suspicions; 139: a statement's replacements
registerItemPanel("duplicates", DuplicatePanel);
registerItemPanel("statements", StatementPanel);

// 058: the utility bills' cost by meter and month, above its table (only a package with utility bills has it)
registerResultTable({ key: "utility", dataset: "utility_cost", label: "Közmű-költség", order: 70, Panel: UtilityPanel });

// 231 (C2d): the pairing capability's element (its page loads only when a case shows it); (C2c) the AI proposal's
const Pairing = lazy(() => import("./Pairing").then((m) => ({ default: m.Pairing })));
const PairingProposal = lazy(() => import("./PairingProposal").then((m) => ({ default: m.PairingProposal })));
registerElement("pairing", { render: lazily(Pairing), status: pairingLine, summary: pairingSummary });
registerElement("pairing_proposal", { render: lazily(PairingProposal) });

// 133: new labels have an English source (the Hungarian translation is in hu-native.json)
registerSettingsSection({
  key: "parties", label: "Own parties", hint: "Whose money is reconciled: companies, associations and people, with their names, tax numbers and accounts",
  order: 30, Panel: lazyPage(() => import("./PartiesPanel").then((m) => m.PartiesPanel)),
});
// 146: the bank exports the statement reader knows, under the description of the processing
registerSettingsPart({
  section: "recipes", title: "Bank files the system reads",
  Panel: lazyPage(() => import("./BankFiles").then((m) => m.BankFilesPanel)),
});
