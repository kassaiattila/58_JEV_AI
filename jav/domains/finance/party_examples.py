"""An invented own party and its bank statements as example material (231, stage U, U1e; the owner's decision of 2026-10-28).

Plain-language summary: the bank statements and the reconciliation belong to an own party, and the live store has only
real ones, so neither process could be tried on invented data. The invented parties (`configs/example_parties.json`)
each have a tax number, accounts and, per account, months of statement lines. A process names the parties as example
material (`{"kind": "own_party", "name": "example_parties"}`): installed, the examples' machine makes each party with its
tax number, its name and its accounts; installed again, it changes nothing. The statements are written as a bank's ISO
20022 camt.053 XML files, every balance and total computed here from the lines, so the statements' reader checks them as
it checks a bank's; the bank statements process offers them as a packet (`configs/examples_bank_statements.json`, made by
`python -m jav.cli examples --set bank_statements --write`). A party goes only while no case and no record names it,
and never one a person made (or one whose tax number a person's party holds).

- `load(name)`: the invented parties (`ExampleParties`).
- `statement_xml(account, n)`: an account's n-th statement as camt.053 XML; `example_packets(titles, name)`: the packets.
- `register()`: the example kind `own_party` for the shared examples library.

Layer: the finance domain; it uses the own parties, their accounts and the shared examples library.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jav.app import parties
from jav.core import cfg, identity, store
from jav.core.user_messages import explained
from jav.domains.finance import party_views, reconcile

__all__ = ["KIND", "ExampleParties", "example_packets", "load", "register", "statement_xml"]

KIND = "own_party"
CAMT = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Line(_Model):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    kind: str = Field(min_length=1, max_length=35)  # the bank's own code of the line's kind (Max35Text)
    credit: Decimal | None = Field(default=None, gt=0)
    debit: Decimal | None = Field(default=None, gt=0)
    partner: str | None = None
    partner_iban: str | None = None
    memo: str | None = None

    @model_validator(mode="after")
    def _one_side(self) -> Line:
        if (self.credit is None) == (self.debit is None):
            raise ValueError("a line is a credit or a debit")
        return self

    @property
    def signed(self) -> Decimal:
        return self.credit if self.credit is not None else -(self.debit or Decimal(0))


class Statement(_Model):
    id: str = Field(min_length=1)
    start: str = Field(alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$")
    opening: Decimal | None = None  # the first statement's; each later one opens with the closing before it
    lines: tuple[Line, ...] = Field(min_length=1)


class Account(_Model):
    iban: str
    kind: str = Field(pattern=r"^(account|card)$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    bank: str
    bic: str
    statements: tuple[Statement, ...] = ()

    @model_validator(mode="after")
    def _opens(self) -> Account:
        if self.statements and self.statements[0].opening is None:
            raise ValueError(f"{self.iban}: the first statement names its opening balance")
        return self


class Party(_Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1)
    tax_number: str
    accounts: tuple[Account, ...] = Field(min_length=1)


class ExampleParties(_Model):
    parties: tuple[Party, ...] = Field(min_length=1)


def load(name: str = "example_parties") -> ExampleParties:
    data = cfg.load(name)
    return ExampleParties.model_validate({k: v for k, v in data.items() if k != "meta"})


def _openings(account: Account) -> list[Decimal]:
    """Each statement's opening balance: the first one's as given, each later one the closing before it."""
    out, balance = [], account.statements[0].opening or Decimal(0)
    for s in account.statements:
        out.append(balance)
        balance += sum((ln.signed for ln in s.lines), Decimal(0))
    return out


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def statement_xml(account: Account, n: int) -> str:
    """The account's n-th statement as a bank's camt.053 XML file: its period, its balances and totals, and per line its
    days, amount, running balance, partner and memo."""
    s, opening = account.statements[n], _openings(account)[n]
    ccy, iban = account.currency, account.iban.replace(" ", "")

    def bal(code: str, amount: Decimal, day: str) -> str:
        return (f'<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy="{ccy}">{_amount(abs(amount))}</Amt>'
                f"<CdtDbtInd>{'DBIT' if amount < 0 else 'CRDT'}</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>")

    entries, balance = [], opening
    for i, ln in enumerate(s.lines, start=1):
        balance += ln.signed
        role = "Dbtr" if ln.credit is not None else "Cdtr"
        party = ""
        if ln.partner:
            acct = f"<{role}Acct><Id><IBAN>{ln.partner_iban.replace(' ', '')}</IBAN></Id></{role}Acct>" if ln.partner_iban else ""
            party = f"<RltdPties><{role}><Nm>{escape(ln.partner)}</Nm></{role}>{acct}</RltdPties>"
        memo = f"<RmtInf><Ustrd>{escape(ln.memo)}</Ustrd></RmtInf>" if ln.memo else ""
        entries.append(
            f'<Ntry><NtryRef>{i}</NtryRef><Amt Ccy="{ccy}">{_amount(abs(ln.signed))}</Amt>'
            f"<CdtDbtInd>{'CRDT' if ln.credit is not None else 'DBIT'}</CdtDbtInd><Sts>BOOK</Sts>"
            f"<BookgDt><Dt>{ln.day}</Dt></BookgDt><ValDt><Dt>{ln.day}</Dt></ValDt>"
            f"<AcctSvcrRef>{s.id.replace('/', '')}{i:04d}</AcctSvcrRef>"
            f"<BkTxCd><Prtry><Cd>{escape(ln.kind)}</Cd></Prtry></BkTxCd>"
            f'<NtryDtls><TxDtls><AmtDtls><PrtryAmt><Tp>POSTBALANCE</Tp><Amt Ccy="{ccy}">{_amount(balance)}</Amt></PrtryAmt>'
            f"</AmtDtls>{party}{memo}</TxDtls></NtryDtls></Ntry>")
    credits = sum((ln.signed for ln in s.lines if ln.credit is not None), Decimal(0))
    debits = -sum((ln.signed for ln in s.lines if ln.debit is not None), Decimal(0))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="{CAMT}"><BkToCstmrStmt>'
            f"<GrpHdr><MsgId>{s.id.replace('/', '')}</MsgId><CreDtTm>{s.end}T23:59:59</CreDtTm></GrpHdr>"
            f"<Stmt><Id>{escape(s.id)}</Id><CreDtTm>{s.end}T23:59:59</CreDtTm>"
            f"<FrToDt><FrDtTm>{s.start}T00:00:00</FrDtTm><ToDtTm>{s.end}T23:59:59</ToDtTm></FrToDt>"
            f"<Acct><Id><IBAN>{iban}</IBAN></Id><Ccy>{ccy}</Ccy>"
            f"<Svcr><FinInstnId><BIC>{account.bic}</BIC><Nm>{escape(account.bank)}</Nm></FinInstnId></Svcr></Acct>"
            f"{bal('OPBD', opening, s.start)}{bal('CLBD', balance, s.end)}"
            f"<TxsSummry><TtlCdtNtries><Sum>{_amount(credits)}</Sum></TtlCdtNtries>"
            f"<TtlDbtNtries><Sum>{_amount(debits)}</Sum></TtlDbtNtries></TxsSummry>"
            f"{''.join(entries)}</Stmt></BkToCstmrStmt></Document>\n")


def example_packets(titles: dict[str, str], name: str = "example_parties") -> list[dict[str, Any]]:
    """One packet per invented party: its accounts' statements as camt.053 files, written as they are."""
    packets = []
    for party in load(name).parties:
        documents = []
        for account in party.accounts:
            digits = account.iban.replace(" ", "")[4:]
            documents += [{"file": f"{s.end.replace('-', '')}_{digits}_camt053.xml", "text": statement_xml(account, n)}
                          for n, s in enumerate(account.statements)]
        packets.append({"id": party.id, "title": titles.get(party.id, f"Invented statements of {party.name}"),
                        "documents": documents})
    return packets


# --- the example kind -------------------------------------------------------------------------------------------------


def _found(party: Party) -> dict[str, Any] | None:
    """The own party holding the invented party's tax number ({party_id, name, made_by_id}), or None."""
    with store.connect() as c:
        held = parties.holder_in(c, "tax", parties.tax_key(party.tax_number))
        if held is None:
            return None
        row = c.execute("SELECT created_by_id FROM own_parties WHERE id=?", (held["party_id"],)).fetchone()
        return {**held, "made_by_id": row["created_by_id"] if row is not None else None}


def _account_keys(party: Party) -> list[str]:
    return [reconcile.account_key(a.iban) for a in party.accounts]


def _holds_accounts(party_id: str, party: Party) -> bool:
    with store.connect() as c:
        held = [parties.holder_in(c, "account", k) for k in _account_keys(party)]
    return all(h is not None and h["party_id"] == party_id for h in held)


def _state(name: str) -> dict[str, Any]:
    from jav.app import examples

    invented = load(name).parties
    found = [(p, _found(p)) for p in invented]
    complete = [f is not None and _holds_accounts(f["party_id"], p) for p, f in found]
    state = examples.INSTALLED if all(complete) else examples.PARTIAL if any(f for _p, f in found) else examples.MISSING
    made = [f for _p, f in found if f is not None]
    return {"state": state, "example": bool(made) and all(examples.is_example(f["made_by_id"]) for f in made),
            "title": ", ".join(p.name for p in invented)}


def _install(name: str, maker: identity.Who, approver: identity.Who) -> None:
    """Each invented party made by `maker` with its tax number, its name and its accounts; a party already there gets
    the accounts it lacks, unless a person made it (the examples never change a person's things)."""
    from jav.app import examples

    del approver  # a party is no versioned thing a second person makes active
    for party in load(name).parties:
        found = _found(party)
        if found is not None and not examples.is_example(found["made_by_id"]):
            raise explained(examples.ExampleRefused, "the tax number of {{name}} belongs to {{party}}, a party a person made",
                            name=party.name, party=found["name"])
        if found is None:
            party_id = parties.create(party.name, actor=maker, identities=[
                ("tax", parties.tax_key(party.tax_number), party.tax_number), ("name", party.name, party.name)])["id"]
        else:
            party_id = found["party_id"]
        for account in party.accounts:
            with store.connect() as c:
                held = parties.holder_in(c, "account", reconcile.account_key(account.iban))
            if held is not None and held["party_id"] == party_id:
                continue
            try:
                party_views.register_account(party_id, account.iban, kind=account.kind, currencies=[account.currency],
                                             bank=account.bank, actor=maker)
            except parties.PartyError as exc:  # another party holds the account
                raise explained(examples.ExampleRefused, "an account of {{name}} is another party's",
                                name=party.name) from exc


def _remove(name: str, maker_id: str) -> None:
    """Each invented party taken out with its accounts' details, once no case and no record names it and the examples'
    machine made it; otherwise nothing goes."""
    from jav.app import examples
    from jav.core.process import cases

    found = [(p, f) for p in load(name).parties if (f := _found(p)) is not None]
    if refused := [f["name"] for _p, f in found if f["made_by_id"] != maker_id]:
        raise explained(examples.ExampleRefused, "a person made {{things}}: it is not example material to remove",
                        things=", ".join(refused))
    with store.connect() as c:
        if holding := cases.holding_in(c, [f'"{f["party_id"]}"' for _p, f in found]):
            raise explained(examples.ExampleInUse, "the example material stays: the cases {{cases}} keep it",
                            cases=", ".join(holding))
    for party, f in found:
        try:
            parties.delete(f["party_id"], actor=examples.MACHINE)
        except parties.PartyError as exc:  # a package or a workflow names the party
            raise explained(examples.ExampleInUse, "the example material stays: a package or a workflow names {{name}}",
                            name=party.name) from exc
        with store.connect() as c:
            c.executemany("DELETE FROM own_accounts WHERE key=?", [(k,) for k in _account_keys(party)])


def register() -> None:
    from jav.app import examples

    examples.register(KIND, examples.ExampleKind(_state, _install, _remove))
