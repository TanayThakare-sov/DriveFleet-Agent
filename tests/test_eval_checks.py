"""The eval harness's scoring must itself be trustworthy: feed it known good/bad answers."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("run_eval", Path(__file__).resolve().parents[1] / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)
check = run_eval.check_answer


def test_number_matching_handles_commas_and_word_boundaries():
    assert run_eval.has_value("There are 1,234 drives", 1234)
    assert not run_eval.has_value("There are 12345 drives", 1234)
    assert not run_eval.has_value("about 600.5 drives", 600)


def test_sql_values():
    c = {"type": "sql_values", "sql": "SELECT COUNT(*) FROM drives"}
    assert check(c, "The fleet has 600 drives.")[0]
    assert not check(c, "The fleet has 500 drives.")[0]


def test_risk_tier():
    c = {"type": "risk_tier", "serial": "SN00157"}
    assert check(c, "SN00157 is high risk (58%).")[0]
    assert not check(c, "SN00157 looks low risk.")[0]
    assert not check(c, "No idea.")[0]


def test_warranty_status():
    c_active = {"type": "warranty_status", "serial": "SN00157"}   # still under warranty
    c_expired = {"type": "warranty_status", "serial": "SN00004"}  # expired
    assert check(c_active, "Yes, it is still under warranty until 2026-11-28.")[0]
    assert not check(c_active, "Its warranty has expired.")[0]
    assert check(c_expired, "The warranty expired on 2025-12-03... no longer covered.")[0]
    assert not check(c_expired, "It is still under warranty.")[0]


def test_multi_tool_ground_truth_is_consistent():
    serials = run_eval.high_risk_under_warranty()
    assert serials and check({"type": "high_risk_warranty_count"}, f"{len(serials)} drives")[0]
    assert check({"type": "high_risk_warranty_top", "n": 3}, ", ".join(serials[:3]))[0]
    assert not check({"type": "high_risk_warranty_top", "n": 3}, serials[0])[0]
