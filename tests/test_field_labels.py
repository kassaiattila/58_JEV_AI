"""Mezőnév-szótár (058): minden típuscsomag minden mezőjének és tételes-lista oszlopának van magyar neve, így a
felületen és a letöltésekben nem jelenik meg gépi név. Új típus vagy mező felvételekor ez a teszt jelez."""

from jav import cfg, typepack


def test_every_typepack_field_has_a_hungarian_label():
    labels = cfg.load("field_labels")["fields"]
    missing = sorted({f"{key}.{f}" for key in typepack.keys() for f in typepack.get(key).fields if f not in labels})
    assert missing == []


def test_every_list_column_has_a_hungarian_label():
    columns = cfg.load("field_labels")["columns"]
    missing = sorted({f"{key}.{lf}.{c}" for key in typepack.keys()
                      for lf, cols in typepack.get(key).list_fields.items() for c in cols if c not in columns})
    assert missing == []


def test_labels_are_unique_per_meaning():
    # két különböző mező ugyanazzal a névvel a táblázatban összetéveszthető lenne
    labels = cfg.load("field_labels")["fields"]
    seen: dict[str, str] = {}
    clashes = []
    for key, label in labels.items():
        if label in seen:
            clashes.append((seen[label], key, label))
        seen.setdefault(label, key)
    assert clashes == []
