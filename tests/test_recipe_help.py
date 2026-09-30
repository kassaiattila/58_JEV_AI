"""063: the recipe explanations (`configs/recipe_help.json`) — every recipe, setting and selectable value has an
explanatory text, the service delivers them alongside the recipes, and they do not affect the recipe fingerprint
(existing packages do not show an "a recept változott" (the recipe changed) warning)."""

from fastapi.testclient import TestClient

from jav import api, cfg, work, work_views


def test_every_recipe_param_and_option_is_explained():
    help_ = work_views.recipe_help()
    for r in work.recipes():
        assert help_["recipes"][r["id"]]["when"].strip(), r["id"]
        for name, spec in r["params"].items():
            p = help_["params"][name]
            assert p["help"].strip(), name
            for value in spec.get("allowed") or []:
                assert p["options"][value].strip(), f"{name}={value}"


def test_help_is_separate_from_the_recipe_fingerprint():
    # the explanation is not part of the recipe: the fingerprint recorded at assignment stays unchanged
    for r in work.recipes():
        assert "help" not in r and "when" not in r
    assert cfg.load("recipe_help")["meta"]["name"] == "recipe_help"


def test_service_returns_help_next_to_recipes(tmp_path):
    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    body = c.get("/api/recipes").json()
    assert {r["id"] for r in body["recipes"]} <= set(body["help"]["recipes"])
    assert body["help"]["params"]["arm"]["options"]["auto"]
