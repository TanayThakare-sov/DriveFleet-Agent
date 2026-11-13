from drivefleet.tools import list_high_risk_drives, predict_drive_risk


def test_predict_known_drive():
    r = predict_drive_risk("SN00157")
    assert r["risk_tier"] in {"low", "medium", "high"}
    assert 0.0 <= r["failure_probability"] <= 1.0
    assert r["model_name"]


def test_predict_is_case_insensitive_and_unknown_handled():
    assert predict_drive_risk("sn00157")["serial"] == "SN00157"
    assert "error" in predict_drive_risk("SN99999")


def test_high_risk_list_sorted_and_active_only():
    out = list_high_risk_drives("high", 500)
    probs = [d["failure_probability"] for d in out["drives"]]
    assert probs == sorted(probs, reverse=True)
    assert out["total_matching"] == len(out["drives"]) > 0
    assert all(d["risk_tier"] == "high" for d in out["drives"])
    assert all(predict_drive_risk(d["serial"])["status"] == "active" for d in out["drives"][:5])


def test_limit_and_bad_tier():
    assert list_high_risk_drives("medium", 3)["returned"] == 3
    assert "error" in list_high_risk_drives("extreme")
