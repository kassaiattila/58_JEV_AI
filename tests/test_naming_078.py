"""Content-based file names (078).

Synthetic values and PDFs, a fake JEV client, no paid calls. Covered: how a name is built from the corrected values,
when a copy goes to the review folder, the configuration's coverage of every type, and on a whole run the ZIP, the
output folder (never overwriting, never overlapping a watched folder) and that the originals stay untouched.
"""

import csv
import hashlib
import io
import zipfile

import pytest

from jav import cfg, cli, datasets, naming, store, typepack
from jav.runtime import worker
from tests import test_api
from tests.test_api import HUMAN, _cli_json, _ready_wp, _start

env = test_api.env


def _rules():
    return naming.rules()


# --- parts ----------------------------------------------------------------------------------------------------


def test_safe_part_folds_accents_and_keeps_only_letters_digits_and_hyphens():
    assert naming.safe_part("Kovács és Társa Kft.") == "Kovacs-es-Tarsa-Kft"
    assert naming.safe_part("Őrség  Ügynökség / Zrt") == "Orseg-Ugynokseg-Zrt"
    assert naming.safe_part("SZ/2026/001_234") == "SZ-2026-001-234"  # "_" only ever separates the parts
    assert naming.safe_part("Straße Øresund Łódź") == "Strasse-Oresund-Lodz"
    assert naming.safe_part("  ...  ") is None and naming.safe_part(None) is None


def test_safe_part_cuts_at_a_word_boundary_within_the_limit():
    assert naming.safe_part("Minta Kereskedelmi és Szolgáltató Korlátolt Felelősségű Társaság", limit=20) == "Minta-Kereskedelmi"
    assert naming.safe_part("Minta Kereskedelmi Kft", limit=19) == "Minta-Kereskedelmi"
    assert naming.safe_part("Mintaszolgaltatokozpont Kft", limit=10) == "Mintaszolg"  # one long word: cut inside it


def test_legal_forms_are_shortened_in_names_only():
    r = _rules()
    long = "Fővárosi Vízművek Zártkörűen Működő Részvénytársaság"
    assert naming.format_value(long, "name", rules=r) == "Fovarosi-Vizmuvek-Zrt"
    assert naming.format_value("Minta KORLÁTOLT FELELŐSSÉGŰ TÁRSASÁG", "name", rules=r) == "Minta-Kft"
    assert naming.format_value("Example Operations Limited", "name", rules=r) == "Example-Operations-Ltd"
    assert naming.format_value("Részvénytársaság utca 1.", "address", "street", rules=r) == "Reszvenytarsasag-utca-1"  # not a name


def test_a_street_without_a_comma_drops_the_postcode_and_town_and_has_one_case():
    assert naming.format_value("1155 BUDAPEST SZÉCHENYI ÚT 101", "address", "street") == "Szechenyi-ut-101"
    assert naming.format_value("1155 Budapest, Széchenyi út 101.", "address", "street") == "Szechenyi-ut-101"
    assert naming.format_value("Széchenyi út 101", "address", "street") == "Szechenyi-ut-101"


def test_dates_become_iso_and_nonsense_is_missing():
    assert naming.format_value("2026-09-12", "date") == "2026-09-12"
    assert naming.format_value("2026.09.12.", "date") == "2026-09-12"
    assert naming.format_value("2026-10-05T19:00", "text", "date") == "2026-10-05"
    assert naming.format_value("2026-13-40", "date") is None
    assert naming.format_value("jövő héten", "date") is None


def test_modifiers_last_digits_and_street():
    assert naming.format_value("HU12 1070 0024 1234 5678 9012 3456", "iban", "last8") == "90123456"
    assert naming.format_value("12", "text", "last8") is None  # too short to identify an account
    assert naming.format_value("1234 Budapest, Minta utca 12.", "address", "street") == "Minta-utca-12"
    assert naming.format_value("Minta utca 12.", "address", "street") == "Minta-utca-12"
    assert naming.format_value("1234 Budapest", "address", "street") == "1234-budapest"  # no street: the town stays
    assert naming.format_value("  ", "address", "street") is None


# --- whole names ------------------------------------------------------------------------------------------------

INVOICE = {"issue_date": "2026-09-12", "fulfillment_date": "2026-09-10", "supplier_name": "Minta Kft.",
           "invoice_number": "SZ-2026/001234"}
INVOICE_KINDS = {"issue_date": "date", "fulfillment_date": "date", "supplier_name": "name", "invoice_number": "invoice_number"}


def test_invoice_name_is_date_type_partner_identifier():
    n = naming.name_for("invoice_hu", INVOICE, INVOICE_KINDS, original="scan_0001.PDF", rules=_rules())
    assert n.stem == "2026-09-12_SZAMLA_Minta-Kft_SZ-2026-001234" and n.ext == ".pdf"
    assert n.missing == () and n.fields == ("issue_date", "supplier_name", "invoice_number")  # the fields actually used


def test_the_first_non_empty_alternative_is_used():
    values = {**INVOICE, "issue_date": None}
    n = naming.name_for("invoice_hu", values, INVOICE_KINDS, original="a.pdf", rules=_rules())
    assert n.stem.startswith("2026-09-10_SZAMLA_") and n.missing == ()


def test_a_missing_field_gets_a_placeholder_and_is_reported():
    values = {**INVOICE, "invoice_number": ""}
    n = naming.name_for("invoice_hu", values, INVOICE_KINDS, original="a.pdf", rules=_rules())
    assert n.stem == "2026-09-12_SZAMLA_Minta-Kft_ismeretlen" and n.missing == ("invoice_number",)
    none = naming.name_for("invoice_hu", {}, INVOICE_KINDS, original="a.pdf", rules=_rules())
    assert none.stem == "datum-nelkul_SZAMLA_ismeretlen_ismeretlen"
    assert set(none.missing) == {"issue_date", "supplier_name", "invoice_number"}


def test_statement_name_carries_the_period_bank_currency_and_account_end():
    values = {"period_start": "2026-08-01", "period_end": "2026-08-31", "currency": "HUF", "account_no": "10700024-12345678-51100005"}
    kinds = {"period_start": "date", "period_end": "date", "currency": "currency", "account_no": "text"}
    n = naming.name_for("statement_cib", values, kinds, original="kivonat.pdf", rules=_rules())
    assert n.stem == "2026-08-01_2026-08-31_KIVONAT_CIB_HUF_51100005"


def test_utility_name_uses_the_billing_period_and_the_street():
    values = {"billing_period_start": "2026-08-01", "issue_date": "2026-09-03", "supplier_name": "Minta Energia Zrt.",
              "consumption_address": "1111 Budapest, Példa utca 12."}
    kinds = {"billing_period_start": "date", "issue_date": "date", "supplier_name": "name", "consumption_address": "address"}
    n = naming.name_for("villamos_energia_szamla", values, kinds, original="x.pdf", rules=_rules())
    assert n.stem == "2026-08-01_VILLANY_Minta-Energia-Zrt_Pelda-utca-12"


def test_a_type_without_a_pattern_uses_the_default_with_the_original_name():
    n = naming.name_for("contract", {}, {}, original="Bérleti szerződés (aláírt).pdf", rules=_rules())
    assert n.stem == "datum-nelkul_SZERZODES_Berleti-szerzodes-alairt" and n.missing == ()
    unknown = naming.name_for(None, {}, {}, original="beolvasas.pdf", rules=_rules())
    assert unknown.stem == "datum-nelkul_ISMERETLEN_beolvasas" and unknown.type_unknown


def test_the_stem_is_capped_and_the_extension_kept_lower_case():
    values = {**INVOICE, "supplier_name": "A" * 300, "invoice_number": "9" * 300}
    n = naming.name_for("invoice_hu", values, INVOICE_KINDS, original="x.Pdf", rules=_rules())
    assert len(n.stem) <= _rules().stem_max_chars and n.ext == ".pdf" and not n.stem.endswith(("-", "_"))
    assert naming.name_for("contract", {}, {}, original="noext", rules=_rules()).ext == ""


def test_collisions_get_a_numbered_suffix_case_insensitively():
    used: set[str] = set()
    assert naming.unique("", "a.pdf", used) == "a.pdf"
    assert naming.unique("", "A.pdf", used) == "A__2.pdf"
    assert naming.unique("", "a.pdf", used) == "a__3.pdf"
    assert naming.unique("ellenorzendo", "a.pdf", used) == "a.pdf"  # another folder: no clash


# --- review rule ------------------------------------------------------------------------------------------------


def _review(reasons, *, corrected=(), missing=(), doc_type="invoice_hu", fields=INVOICE):
    n = naming.name_for(doc_type, {k: v for k, v in fields.items() if k not in missing}, INVOICE_KINDS, original="a.pdf", rules=_rules())
    return naming.review_reasons(n, open_reasons=reasons, corrected=corrected, kinds=INVOICE_KINDS, rules=_rules())


def test_a_to_do_on_a_name_field_sends_the_copy_to_review_unless_a_person_corrected_it():
    assert _review(["pick:low_conf:invoice_number:0.53"]) == ["todo:invoice_number"]
    assert _review(["pick:low_conf:invoice_number:0.53"], corrected=["invoice_number"]) == []
    assert _review(["pick:low_conf:payment_iban:0.53", "validator:totals.mismatch"]) == []  # not part of the name


def test_scoped_to_dos_reach_their_parts():
    assert _review(["validator:dates.unparseable"]) == ["todo:issue_date"]  # only the date the name was built from
    assert _review(["pick:low_conf:fulfillment_date:0.40"]) == []  # the fallback date was not used
    assert _review(["parties:same_tax_id"]) == ["todo:supplier_name"]
    assert _review(["detect:low_conf:unknown:0.96"]) == ["type"]
    assert _review(["jev_unavailable:TypeSafeBadRequestError:400:max_tokens_exceeded"]) == ["todo:*"]
    assert _review(["llm:failed:TypeError"], corrected=list(INVOICE)) == ["todo:*"]  # the whole document is in doubt


def test_missing_fields_and_an_unknown_type_are_review_reasons():
    assert _review([], missing=("invoice_number",)) == ["missing:invoice_number"]
    assert _review([], doc_type=None, fields={}) == ["type"]


def test_review_texts_name_the_field_in_everyday_words():
    labels = cfg.load("field_labels")["fields"]
    text = naming.reason_text(["missing:invoice_number", "todo:supplier_name", "type", "todo:*", "not_done:failed"])
    assert labels["invoice_number"] in text and labels["supplier_name"] in text and ";" in text


# --- configuration ----------------------------------------------------------------------------------------------


def test_every_type_pack_and_detection_type_has_a_token():
    doc_types = cfg.load("doc_types")
    keys = set(typepack.keys()) | {t["key"] for t in doc_types["types"]} | {doc_types["unknown_key"]}
    missing = sorted(k for k in keys if k not in _rules().types)
    assert missing == []


def test_every_pattern_names_only_fields_of_its_type_pack():
    for key, spec in _rules().types.items():
        if spec.pattern is None:
            continue
        pack = typepack.get(key)
        for part in spec.parts:
            for f in part.fields:
                assert f in pack.fields, f"{key}: unknown field {f}"


def test_a_broken_pattern_is_rejected_on_load():
    raw = cfg.load("naming")
    bad = {**raw, "types": {**raw["types"], "invoice_hu": {"token": "SZAMLA", "pattern": "{issue_date}/{supplier_name}"}}}
    with pytest.raises(naming.NamingConfigError):
        naming.parse_rules(bad)
    bad2 = {**raw, "types": {**raw["types"], "invoice_hu": {"token": "SZAMLA", "pattern": "{issue_date:nincs}"}}}
    with pytest.raises(naming.NamingConfigError):
        naming.parse_rules(bad2)


def test_a_too_long_output_path_is_refused_and_a_long_one_shortens_the_name():
    assert naming._fit("2026-09-12_SZAMLA_" + "A" * 80, ".pdf", "", 60).startswith("2026-09-12_SZAMLA_")
    assert len(naming._fit("x" * 100, ".pdf", "ellenorzendo", 70)) <= 70 - len("ellenorzendo/") - len(".pdf") - 4
    with pytest.raises(ValueError, match="too long"):
        naming._fit("x" * 100, ".pdf", "ellenorzendo", 30)


# --- a whole run ------------------------------------------------------------------------------------------------

READY = "2026-09-01_SZAMLA_Minta-Kereskedelmi-Kft_MINTA-2026-001.pdf"


def _run(c, folder):
    wp = _ready_wp(c, folder)
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    return wp, run_id


def _correct_first(c, wp, run_id):
    """A person fixes the two name fields the fake model got wrong on the first invoice."""
    item_id = next(i["item_id"] for i in wp["items"] if i["source_path"].endswith("szamla_1.pdf"))
    r = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN, json={
        "fields": {"supplier_name": "Minta Kereskedelmi Kft.", "invoice_number": "MINTA-2026-001"}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    return item_id


def _digests(folder):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sorted(folder.iterdir())}


def test_names_follow_the_corrections_and_uncertain_copies_go_to_review(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    before = naming.plan(run_id)
    assert [x.status for x in before] == ["review", "review"]  # the fake model found no invoice number
    assert "missing:invoice_number" in before[0].reasons and before[1].filename.endswith("__2.pdf")  # same name twice
    first = _correct_first(c, wp, run_id)
    after = {x.item_id: x for x in naming.plan(run_id)}
    assert after[first].status == "ready" and after[first].path == READY and after[first].reasons == ()
    other = next(x for k, x in after.items() if k != first)
    assert other.status == "review" and other.path.startswith("ellenorzendo/")

    # the same in the result view, with the reasons in everyday words
    assert "file_names" in c.get(f"/api/runs/{run_id}").json()["tables"]
    body = c.post("/api/datasets/file_names/query", json={"scope": {"run_id": run_id}, "query": {}}).json()
    rows = {r["item_id"]: r for r in body["rows"]}
    assert rows[first]["filename"] == READY and rows[first]["status"] == "ready" and rows[first]["why"] is None
    labels = cfg.load("field_labels")["fields"]
    assert labels["invoice_number"] in rows[other.item_id]["why"]
    assert next(col for col in body["columns"] if col["key"] == "status")["labels"]["review"] == "Ellenőrzendő"


def test_zip_holds_exact_copies_and_a_manifest_and_leaves_the_originals_alone(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)
    originals = _digests(env["folder"])
    r = c.get(f"/api/runs/{run_id}/named-copies.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["x-named-ready"] == "1" and r.headers["x-named-review"] == "1" and r.headers["x-named-skipped"] == "0"
    assert "Mesterseges-szamlak_" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = sorted(z.namelist())
    assert READY in names and "jegyzek.csv" in names and sum(n.startswith("ellenorzendo/") for n in names) == 1
    assert hashlib.sha256(z.read(READY)).hexdigest() == first  # the copy is byte for byte the processed document
    manifest = z.read("jegyzek.csv")
    assert manifest.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(manifest.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:4] == ["Új fájl", "Állapot", "Miért ellenőrzendő", "Eredeti fájlnév"]
    assert {r[0]: r[3] for r in rows[1:]}[READY] == "szamla_1.pdf" and len(rows) == 3
    assert _digests(env["folder"]) == originals  # the originals: same bytes, same modification time
    assert c.get(f"/api/runs/run-{'0' * len(run_id[4:])}/named-copies.zip").status_code == 404


def test_a_source_changed_since_it_was_added_is_left_out(env):
    c = env["client"]
    _wp, run_id = _run(c, env["folder"])
    (env["folder"] / "szamla_2.pdf").write_bytes(b"%PDF-1.4 megvaltozott")
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/runs/{run_id}/named-copies.zip").content))
    assert len([n for n in z.namelist() if n.endswith(".pdf")]) == 1
    rows = list(csv.reader(io.StringIO(z.read("jegyzek.csv").decode("utf-8-sig")), delimiter=";"))
    skipped = [r for r in rows[1:] if r[1] == "kimaradt"]
    assert len(skipped) == 1 and skipped[0][0] == "" and skipped[0][3] == "szamla_2.pdf" and "megváltozott" in skipped[0][2]


def test_the_output_folder_gets_a_new_subfolder_each_time_and_nothing_is_overwritten(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    _correct_first(c, wp, run_id)
    none = c.post(f"/api/runs/{run_id}/named-copies", headers=HUMAN, json={})
    assert none.status_code == 422 and none.json()["error"] == "no_output_folder"  # the UI names it in Hungarian
    out = env["tmp"] / "kimenet"
    out.mkdir()
    r = c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(out)})
    assert r.status_code == 200 and r.json()["path"] == str(out.resolve())
    assert c.get("/api/settings/output-folder").json()["path"] == str(out.resolve())

    first = c.post(f"/api/runs/{run_id}/named-copies", headers=HUMAN, json={})
    assert first.status_code == 200, first.text
    res = first.json()
    target = out / f"Mesterseges-szamlak_{run_id}"
    assert res["path"] == str(target.resolve()) and (res["ready"], res["review"], res["skipped"]) == (1, 1, 0)
    assert (target / READY).is_file() and (target / "jegyzek.csv").is_file() and len(list((target / "ellenorzendo").iterdir())) == 1
    second = c.post(f"/api/runs/{run_id}/named-copies", headers=HUMAN, json={}).json()
    assert second["path"] == str((out / f"Mesterseges-szamlak_{run_id}__2").resolve())
    assert (target / READY).is_file()  # the first copy set is untouched
    assert c.post(f"/api/runs/{run_id}/named-copies", json={}).status_code == 422  # a person must be named

    deep = out / ("m" * max(1, 200 - len(str(out.resolve())) - 1))  # a 200-character folder: the names would not fit into 250
    deep.mkdir(parents=True)
    assert c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(deep)}).status_code == 200
    too_long = c.post(f"/api/runs/{run_id}/named-copies", headers=HUMAN, json={})
    assert too_long.status_code == 422 and "too long" in too_long.json()["message"]
    assert list(deep.iterdir()) == []  # no empty subfolder is left behind

    assert c.put("/api/settings/output-folder", headers=HUMAN, json={"path": ""}).json()["path"] is None


def test_the_output_folder_and_the_watched_folders_never_overlap(env):
    c = env["client"]
    watched = env["root"] / "figyelt"
    (watched / "belul").mkdir(parents=True)
    r = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"name": "Figyelt", "path": str(watched)}]})
    assert r.status_code == 200, r.text
    inside = c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(watched / "belul")})
    assert inside.status_code == 422 and inside.json()["error"] == "folder_overlap" and "watched folder" in inside.json()["message"]
    around = c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(env["root"])})
    assert around.status_code == 422  # it would contain the watched folder
    assert c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(env["tmp"] / "nincs")}).status_code == 422

    out = env["tmp"] / "kimenet"
    (out / "al").mkdir(parents=True)
    assert c.put("/api/settings/output-folder", headers=HUMAN, json={"path": str(out)}).status_code == 200
    r = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"name": "Rossz", "path": str(out / "al")}]})
    assert r.status_code == 422 and r.json()["error"] == "folder_overlap" and "output folder" in r.json()["message"]


def test_the_command_line_lists_names_and_writes_a_new_zip_only(env, capsys):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    _correct_first(c, wp, run_id)
    listed = _cli_json(capsys, "run-names", run_id)
    assert [x["status"] for x in listed["copies"]].count("ready") == 1 and "written" not in listed
    target = env["tmp"] / "masolatok.zip"
    written = _cli_json(capsys, "run-names", run_id, "--zip", str(target))
    assert written["written"]["ready"] == 1 and READY in zipfile.ZipFile(target).namelist()
    with pytest.raises(FileExistsError):  # an existing file is never overwritten
        cli.main(["run-names", run_id, "--zip", str(target)])


def test_a_document_without_extracted_data_is_named_by_its_recognised_category(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    item_id = next(i["item_id"] for i in wp["items"] if i["source_path"].endswith("szamla_1.pdf"))
    with store.connect() as conn:  # as if detection had found a contract and no extraction ran
        conn.execute("DELETE FROM datapoints WHERE doc_id=?", (item_id,))
        conn.execute("UPDATE documents SET doc_type='contract' WHERE doc_id=?", (item_id,))
    datasets.clear_cache()
    copy = next(x for x in naming.plan(run_id) if x.item_id == item_id)
    assert copy.path == "datum-nelkul_SZERZODES_szamla-1.pdf" and copy.status == "ready"  # "_" only separates parts
