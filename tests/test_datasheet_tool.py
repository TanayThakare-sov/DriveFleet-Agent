import re

from drivefleet.config import get_settings
from drivefleet.seed import MODELS
from drivefleet.tools import search_datasheets


def test_warranty_question_hits_right_model_and_section():
    top = search_datasheets("What's the warranty on the Orion O12?")["results"][0]
    assert top["model"] == "Orion O12" and top["section"] == "Warranty"
    assert "60 months" in top["text"]


def test_model_filter_applied():
    res = search_datasheets("operating temperature Atlas A20", top_k=5)["results"]
    assert res and all(r["model"] == "Atlas A20" for r in res)


def test_unnamed_model_searches_everything():
    models = {r["model"] for r in search_datasheets("helium sealed drive", top_k=5)["results"]}
    assert "Atlas A20" in models


def test_datasheets_match_database_warranty():
    """Datasheet warranty terms must agree with drive_models.warranty_months."""
    d = get_settings().datasheet_dir
    for _id, name, *_rest, warranty_months in MODELS:
        text = next(p for p in d.glob("*.md") if p.read_text().startswith(f"# {name} Datasheet")).read_text()
        assert re.search(rf"warranty of {warranty_months} months", text), name
