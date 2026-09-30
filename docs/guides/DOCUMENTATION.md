# Documentation standard

**In force:** since 2026-09-27 (040); language rules since 2026-09-30 (073). **Audience:** the model doing the development work, and the project owner. Older documents stay where they are; this standard applies to every new or changed document.

## Plain-language summary

The same status used to be written down in five places (the Claude instructions, the README, the backlog, the handoff and the entry page), and the copies drifted apart. Now every kind of information has exactly one home, and every other place links to it. Current and historical material are kept apart, and generated pages are never written by hand.

Since 2026-09-29 (070, the owner's decision) documents fall into two groups. **Codebase documents** go into git and to GitHub together with the code: what the system can do, how it is built, how to install and develop it. **Internal working documents** (handoffs, plans, reports, backlog, decisions log, roadmap) exist only on the development machine: git does not track them, and the daily backup copies them.

Since 2026-09-30 (073, the owner's decision) **everything that reaches GitHub is written in native-level English**: codebase documents, code, comments, commit and tag messages. Internal working documents stay in Hungarian.

## 1. Ground rules

1. **One piece of information, one place.** If something would have to be written in two places, one of them becomes a link.
2. **Current and historical material are separate.** The current state lives in the entry page, the backlog and the latest handoff. Measurement reports and old handoffs are dated historical records and are never rewritten afterwards.
3. **Generated pages are never edited by hand.** These are the state snapshot, the flow diagrams and the call-site catalogue; run the generating command instead. The state snapshot and the call-site catalogue are built from the local store, so they are local (070). The flow descriptions are codebase documents.
4. **Numbers only with evidence.** Every measured number comes with the location of its raw run or receipt. A document never promises more than the measurement shows.
5. **Language and form (073):**
   - Codebase documents use native-level **British English** (recognise, colour, cancelled), consistent with the English UI translation and its en-GB number and date formats. Terms come from the [glossary](../GLOSSARY.md); a new term goes into the glossary before it is used.
   - Every codebase document starts with a **Plain-language summary** (3–5 sentences). Code identifiers belong in the technical parts, not in the prose.
   - UI elements are named by their English UI label, with the Hungarian label in parentheses on first mention, because the UI shows Hungarian by default: **Approve and release** (*Jóváhagyás és kiadás*).
   - Hungarian text printed on documents (for example *számla sorszáma*, invoice number) is document vocabulary: it is quoted in Hungarian with an English gloss.
   - Internal working documents and everything addressed to the owner are in Hungarian and follow CLAUDE.md §8 (plain language, fixed structure).
6. **A codebase document goes into git together with the code**, in the same commit, when both describe the same change. Internal working documents are never committed (070).
7. **Codebase documents never link to internal working documents** (070), because those do not exist in the repository. If a reference is needed, write it as "text (internal: `reports/…`)", with the path inside `docs/`. Internal documents may link to codebase documents freely. The link test (`tests/test_doc_links.py`) enforces this. The single list of internal paths is `jav/doc_scope.py`; `.gitignore` matches it (`tests/test_doc_scope_070.py`), and the daily backup reads it too. The paths have not changed since 2026-09-29.

## 2. Document types

| Document | Group (070) | Location | Purpose | Does NOT contain | Updated when |
|---|---|---|---|---|---|
| Claude instructions | codebase | `CLAUDE.md` | Standing working rules, commands, structure and pitfalls for the model | Session state, dated progress, measured numbers | A working rule changes |
| README | codebase | `README.md` | What this is, how to start it, what it can do **now**, where to go next; the list of codebase documents | Measurement history (that goes into reports) | A capability or the start-up changes |
| Entry page | internal | `docs/INDEX.md` | Current plan, reading paths, list of internal material (plans, reports, historical documents) | A second backlog | A new plan, report or guide appears |
| State snapshot (generated) | local, generated | `docs/STATE.md` | Config versions, contracts, store, git state; **not in git** (it changes on every run) | Hand-written text | `preflight` / Stop hook |
| Call sites (generated) | local, generated | `docs/callsites/` | Questions and thresholds of the JEV call sites and the local call-log statistics | Hand-written text | `python -m jav.cli docs` |
| Flow description (generated) | codebase | `docs/flows/<flow>/FLOW.md` | Steps and diagram generated from the graph contract | Hand-written text | `python -m jav.cli flows` |
| Backlog | internal | `docs/BACKLOG.md` | The single priority list, with status and plan IDs | Long justifications (those go into the plan) | Every finished task |
| Decisions log | internal | `docs/DECISIONS.md` | The owner's decisions with dates; append-only | Engineering proposals presented as decisions | Every owner decision |
| Glossary | codebase | `docs/GLOSSARY.md` | Every technical term in 1–3 sentences with an example, plus its Hungarian equivalent | Piles of synonyms | **Before** a new term is used |
| Architecture | codebase | `docs/ARCHITECTURE.md` | What actually works; planned parts clearly marked | Planned elements shown as finished | A structural change |
| Plan | internal | `docs/plans/NNN/PLAN.md` | Goal, stages and done criteria of a development round | Raw run data | When accepted and at each stage change (status line) |
| Report | internal | `docs/reports/YYYY-MM-DD-<topic>.md` | Conclusions of a measurement, audit or evaluation; release notes | Results corrected after the fact | Once, when closed |
| Guide | codebase | `docs/guides/<TOPIC>.md` | How to do something (installation, development, using the UI: `USER_GUIDE.md`, the config files: `CONFIGS.md`) | Status and measured numbers | The procedure, the UI or the role of a config file changes; a new config file also updates `CONFIGS.md` (a test checks it) |
| Security notes (071) | codebase | `docs/SECURITY.md` | What protects the system and the data, where personal data lives, what is still open | Keys, personal data, links to internal evidence | A protection is added or changed |
| Changelog (071) | codebase | `CHANGELOG.md` | Releases in brief, understandable for the public | Measurement details (those go into the internal release notes) | Every release |
| Handoff | internal | `docs/handoffs/NNN-YYYY-MM-DD-handoff.md` | Session close: what was done, decisions, next step, commit | An independent priority list, status numbers copied by hand | End of session and end of a stage |

**Retired type:** the `docs/CONTINUE_PROMPT_NNN.md` files. The last section of the handoff says how to continue. Existing files remain as historical material.

**Old root-level reports:** the `docs/*_2026-09-2x.md` files do not move, because many places link to them. The entry page lists them under its historical reports heading. New reports go under `docs/reports/` only.

## 3. Required header of plans and reports

Plans and reports are internal working documents, so their header is in Hungarian:

```markdown
# <Cím>

**Dátum:** ÉÉÉÉ-HH-NN · **Állapot:** javaslat | elfogadva | folyamatban | kész | elavult (→ utód) · **Kör:** NNN · **Commit:** <rövid hash, ha van>

## Laikus összefoglaló
3–5 mondat: cél · mit csináltunk · mit jelent · mi a döntés.
```

In a report this is followed by an evidence line (raw run, receipt, commit) and a validity limit: what the report does not claim.

## 4. Life cycle

- **Superseded:** one sentence goes under the first line of the old document: "Superseded: 2026-…, successor: [link]" (in an internal document, in Hungarian). The document is neither deleted nor rewritten.
- **Moving** a document requires a link check. If many links point to the old location, a one-line pointer file stays there.
- **Plan status:** the status field is updated at each stage change. Progress details go into the backlog, not into the plan.
- **Handoff:** earlier handoffs are never modified. A handoff names the commit hash it refers to.

## 5. End-of-session checklist

1. Did a capability change? → the README's "what it can do now" section.
2. Was a task finished? → its backlog status.
3. Did the owner decide something? → decisions log, handoff, memory.
4. A new technical term? → glossary.
5. A measurement? → a report under `docs/reports/`, with the location of the raw run.
6. `python -m jav.cli preflight` is green → commit (codebase files only) → handoff with the commit hash (the handoff stays local and is not committed).
