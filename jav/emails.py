"""E-mail bemeneti modell (M3): üzenet + csatolmányok, törzs-tisztítás, betöltők.

Két forrás, egy modell:
- **inbox-mappa** (a régi `email-intake-bare` fájl-modellje): `inbox/<mailbox>/<message_id>/message.json` + a
  csatolmány-fájlok ugyanabban a mappában. Ezt írja a `scripts/outlook_pull.ps1` (asztali Outlook, csak olvas).
- **régi intent-golden** (`10_AIFLOW_V4/data/golden/email-intake-bare/intent-golden-s21.json`): 96 valós levél,
  600 karakteres törzs-előnézettel és csatolmány-fájlnevekkel (fájl nélkül). PII: a régi projektben marad,
  csak hivatkozzuk.

A törzs-tisztítás kód (1. szint): idézett/továbbított levélfej levágása, csupasz URL-sorok, üres sorok
összevonása. A Jev a TISZTÍTOTT törzset látja magyar verbatim.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from jav.config import BRIDGE_DATA_ROOT, OLD_DATA_ROOT

OLD_INTENT_GOLDEN = OLD_DATA_ROOT / "golden" / "email-intake-bare" / "intent-golden-s21.json"
DOC_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MAX_BODY_CHARS = 4000
BRIDGE_BODY_LIMIT = 20_000  # a régi Outlook-szkript ennyi karakterig küldi a levél szövegét (jav/ingest_server.py)

# idézett / továbbított levél kezdete: innentől NEM a küldő saját szövege
_QUOTE_HEAD = re.compile(
    r"^\s*("
    r"-{2,}\s*(Original Message|Eredeti üzenet|Forwarded message|Továbbított üzenet)\s*-{2,}"
    r"|From:\s.+|Feladó:\s.+|Von:\s.+"
    r"|On .+ wrote:|.+ írta:|.+ ezt írta \(.+\):"
    r"|_{10,}"
    r")\s*$",
    re.IGNORECASE,
)
_URL_ONLY = re.compile(r"^\s*<?https?://\S+>?\s*$", re.IGNORECASE)
_INLINE_URL = re.compile(r"<https?://[^>\s]+>")
# hírlevél pre-header töltelék és láthatatlan formázó karakterek (U+034F, U+200B-D, U+FEFF, U+00AD, U+2060, NBSP-sor)
_INVISIBLE = re.compile(r"[͏​‌‍⁠﻿­]")
_SIG_START = re.compile(r"^\s*(--\s*$|Üdvözlettel|Tisztelettel|Best regards|Kind regards|Mit freundlichen Grüßen)", re.IGNORECASE)


class Attachment(BaseModel):
    filename: str
    path: str | None = None  # None: csak a fájlnév ismert (régi golden)
    doc_id: str | None = None
    doc_type: str | None = None  # M1 eredménye, ha lefutott
    type_conf: float | None = None
    issuer_hu: float | None = None
    status: str | None = None  # detect final_status: done / needs_ocr / name_only / unsupported

    @property
    def ext(self) -> str:
        return Path(self.filename).suffix.lower()


class EmailMessage(BaseModel):
    message_id: str
    mailbox: str | None = None
    sender: str | None = None
    sender_name: str | None = None
    subject: str = ""
    received_at: str | None = None
    body: str = ""  # nyers törzs (plain text)
    attachments: list[Attachment] = Field(default_factory=list)


@dataclass
class GoldenEmail:
    case_id: str
    expected: str
    source: str
    message: EmailMessage


def _has_quoted_part(text: str) -> bool:
    """Van-e a saját szöveg után idézett / továbbított előzmény (a `clean_body` ettől a sortól vág)."""
    seen_content = False
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _URL_ONLY.match(ln):
            continue
        if _QUOTE_HEAD.match(ln) and seen_content:
            return True
        if ln.strip():
            seen_content = True
    return False


def body_coverage(msg: EmailMessage) -> dict[str, Any]:
    """058 K5.1: a levél szövegéből mennyit látott a szándék-felismerés — kódban, a kérdés építésével azonos szabályokkal.

    `status`: `full` = a levél saját szövege teljesen; `shortened` = csak az eleje (sor- vagy hosszkorlát miatt);
    `capped` = már a letöltéskor elvágódhatott (a régi szkript korlátja). Az idézett előzmény kihagyása nem rövidítés,
    külön jelölve (`quoted_removed`)."""
    from jav.intent import MAX_BODY_LINES, MAX_LINE_CHARS

    own = [ln for ln in clean_body(msg.body, max_chars=10**9).split("\n") if ln.strip()]
    seen = [ln[:MAX_LINE_CHARS] for ln in clean_body(msg.body).split("\n") if ln.strip()][:MAX_BODY_LINES]
    seen_chars, own_chars = sum(len(ln) for ln in seen), sum(len(ln) for ln in own)
    status = "capped" if len(msg.body) >= BRIDGE_BODY_LIMIT else ("shortened" if seen_chars < own_chars else "full")
    return {"status": status, "chars": len(msg.body), "own_chars": own_chars, "seen_chars": seen_chars,
            "seen_lines": len(seen), "quoted_removed": _has_quoted_part(msg.body)}


def clean_body(text: str, *, max_chars: int = MAX_BODY_CHARS) -> str:
    """Az idézett/továbbított rész és a csupasz URL-sorok nélkül; whitespace normalizálva, hossz-korláttal.

    A levágás csak akkor történik, ha az idézet-fej NEM az első értelmes sor (egy 'FW:' levélnek gyakran csak a
    továbbított része van - azt meg kell tartani, különben üres marad a törzs).
    """
    text = _INVISIBLE.sub("", text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " "))
    lines = [_INLINE_URL.sub("", ln).rstrip() for ln in text.split("\n")]
    out: list[str] = []
    seen_content = False
    for ln in lines:
        if _URL_ONLY.match(ln):
            continue
        if _QUOTE_HEAD.match(ln) and seen_content:
            break
        if ln.strip():
            seen_content = True
        out.append(ln.strip())
    # üres sorok összevonása
    collapsed: list[str] = []
    for ln in out:
        if ln or (collapsed and collapsed[-1]):
            collapsed.append(ln)
    body = "\n".join(collapsed).strip()
    return body[:max_chars]


def sender_domain(sender: str | None) -> str | None:
    if not sender or "@" not in sender:
        return None
    return sender.rsplit("@", 1)[1].strip("<> ").lower()


# --- betöltők ------------------------------------------------------------------------------


def _allowed_attachment(path: Path, folder: Path) -> bool:
    """Csatolmány csak a levél saját mappájából, a bridge saját `data/` gyökeréből (048 T2) vagy a régi projekt `data/`
    gyökeréből olvasható (040 K1, F01):
    abszolút vagy `..`-os útvonal a feloldás után sem mutathat ezeken kívülre."""
    try:
        resolved = path.resolve()
    except (OSError, ValueError):
        return False
    roots = (folder.resolve(), Path(BRIDGE_DATA_ROOT).resolve(), Path(OLD_DATA_ROOT).resolve())
    return resolved.is_file() and any(resolved.is_relative_to(r) for r in roots)


# a levél mappájának saját nyilvántartó fájljai — nem csatolmányok (048: a fogadó `receipt.json`-ja és a korábbi verziók)
_BOOKKEEPING = re.compile(r"^(message(\.v\d+)?|receipt)\.json(\.tmp)?$")


def is_bookkeeping_file(name: str) -> bool:
    """A levél mappájának saját nyilvántartó fájlja (a fogadó írja), nem csatolmány (048)."""
    return bool(_BOOKKEEPING.match(name))


def load_message_dir(folder: str | Path) -> EmailMessage:
    """`<folder>/message.json` + a mappa dokumentum-fájljai csatolmányként (a JSON listája elsőbbséget kap)."""
    folder = Path(folder)
    meta = json.loads((folder / "message.json").read_text(encoding="utf-8"))
    listed = meta.get("attachments") or []
    atts: list[Attachment] = []
    if listed:
        for a in listed:
            name = a["filename"] if isinstance(a, dict) else str(a)
            p = folder / (a.get("path") if isinstance(a, dict) and a.get("path") else name)
            atts.append(Attachment(filename=name, path=str(p) if _allowed_attachment(p, folder) else None))
    else:
        for p in sorted(folder.iterdir()):
            if p.is_file() and not _BOOKKEEPING.match(p.name):
                atts.append(Attachment(filename=p.name, path=str(p)))
    return EmailMessage(
        message_id=str(meta.get("message_id") or folder.name),
        mailbox=meta.get("mailbox") or meta.get("account") or folder.parent.name,
        sender=meta.get("sender"),
        sender_name=meta.get("sender_name"),
        subject=meta.get("subject") or "",
        received_at=meta.get("received_at"),
        body=meta.get("body") or meta.get("body_preview") or "",
        attachments=atts,
    )


def iter_inbox(root: str | Path) -> list[Path]:
    """`inbox/<mailbox>/<message_id>/` mappák, amelyekben van message.json."""
    root = Path(root)
    return sorted(p.parent for p in root.glob("*/*/message.json"))


def load_old_golden(path: Path = OLD_INTENT_GOLDEN) -> list[GoldenEmail]:
    """A régi 96 esetes intent-golden a mi modellünkre képezve. A csatolmányoknak csak a neve van."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[GoldenEmail] = []
    for c in data["cases"]:
        p = c["payload"]
        atts = [Attachment(filename=a["filename"] if isinstance(a, dict) else str(a)) for a in (p.get("attachments") or [])]
        msg = EmailMessage(
            message_id=f"golden:{c['name']}",
            mailbox=p.get("account"),
            sender=p.get("sender"),
            subject=p.get("subject") or "",
            body=p.get("body_preview") or "",
            attachments=atts,
        )
        out.append(GoldenEmail(case_id=c["name"], expected=c["expected_intent"], source=c.get("source", "?"), message=msg))
    return out
