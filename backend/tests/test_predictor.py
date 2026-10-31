import pytest

from app.models import RankBasis, RankType
from app.services.predictor import (
    AMBITIOUS, POSSIBLE, STRONGER, PredictorInput, PredictorInputError, classify, predict,
)
from tests.fixtures import add_series, ensure_authority, make_college, set_open_rule

YEARS = {2023: 10000, 2024: 12000, 2025: 11000}


def inp(**kw):
    base = dict(course_code="MBBS", exam_year=2026, rank_type=RankType.official, air=8000, category="OPEN",
                quotas=["AIQ"], preferred_states=["Testland"])
    base.update(kw)
    return PredictorInput(**base)


def results(res):
    return [r for g in res["groups"].values() for r in g]


def test_classify_thresholds():
    closings = [10000, 12000, 11000]
    assert classify(8000, 8000, closings) == STRONGER        # ≤ 0.9 × toughest (9000)
    assert classify(9500, 9500, closings) == POSSIBLE         # inside 10000–12000 range
    assert classify(11900, 11900, closings) == POSSIBLE
    assert classify(13000, 13000, closings) == AMBITIOUS      # ≤ 1.15 × most lenient (13800)
    assert classify(14000, 14000, closings) is None


@pytest.mark.parametrize("air,label", [(8000, STRONGER), (11500, POSSIBLE), (13000, AMBITIOUS)])
def test_fit_labels_and_explanation(db, air, label):
    c = make_college(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", YEARS)
    res = predict(db, inp(air=air))
    [r] = results(res)
    assert r["historical_fit"] == label
    assert r["college_id"] == c.id
    assert [h["closing_rank"] for h in r["history"]] == [10000, 12000, 11000]  # final round per year
    assert r["years_considered"] == [2023, 2024, 2025]
    assert r["counselling_authority"] == "MCC" and r["quota"] == "AIQ" and r["category_used"] == "OPEN"
    assert "guarantee" in res["disclaimer"].lower()
    assert "probab" not in r["explanation"].lower()


def test_rank_far_beyond_history_is_excluded(db):
    c = make_college(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", YEARS)
    res = predict(db, inp(air=50000))
    assert results(res) == []
    assert any("closing ranks" in e["reason"] for e in res["excluded"])


def test_current_and_future_years_are_not_used(db):
    c = make_college(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", {**YEARS, 2026: 500})
    [r] = results(predict(db, inp(air=8000)))
    assert 2026 not in r["years_considered"]


def test_routes_are_never_mixed(db):
    c = make_college(db)
    ensure_authority(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", YEARS)
    add_series(db, c, "TST-STATE", "STATE", "OPEN", {2025: 30000}, domicile=True)
    res = predict(db, inp(air=8000, quotas=["AIQ"], domicile_state="Testland"))
    assert {(r["counselling_authority"], r["quota"]) for r in results(res)} == {("MCC", "AIQ")}

    res = predict(db, inp(air=8000, quotas=["AIQ", "STATE"], domicile_state="Testland"))
    rows = results(res)
    assert {(r["counselling_authority"], r["quota"]) for r in rows} == {("MCC", "AIQ"), ("TST-STATE", "STATE")}
    state_row = next(r for r in rows if r["quota"] == "STATE")
    assert [h["closing_rank"] for h in state_row["history"]] == [30000]  # no AIQ data leaks in


def test_domicile_required_state_quota(db):
    c = make_college(db)
    ensure_authority(db)
    add_series(db, c, "TST-STATE", "STATE", "OPEN", YEARS, domicile=True)
    res = predict(db, inp(quotas=["STATE"], domicile_state="Elsewhere"))
    assert results(res) == []
    assert any("domicile" in e["reason"] for e in res["excluded"])
    assert len(results(predict(db, inp(quotas=["STATE"], domicile_state="Testland")))) == 1


def test_state_rank_basis_needs_state_rank(db):
    c = make_college(db)
    ensure_authority(db)
    add_series(db, c, "TST-STATE", "STATE", "OPEN", {2025: 900}, basis=RankBasis.STATE_RANK, domicile=True)
    res = predict(db, inp(quotas=["STATE"], domicile_state="Testland", air=8000))
    assert results(res) == []
    assert any("state rank" in e["reason"] for e in res["excluded"])
    [r] = results(predict(db, inp(quotas=["STATE"], domicile_state="Testland", air=8000, state_rank=500)))
    assert r["rank_basis"] == "STATE_RANK" and "State rank 500" in r["student_rank_display"]


def test_reserved_category_uses_own_rows_and_open_only_with_rule(db):
    c = make_college(db)
    ensure_authority(db, code="TST-NORULE")
    db.flush()
    from app.models import CounsellingAuthority
    a = db.query(CounsellingAuthority).filter_by(code="TST-NORULE").one()
    a.quotas = ["STATE"]
    add_series(db, c, "TST-NORULE", "STATE", "OPEN", {2025: 9000})
    add_series(db, c, "TST-NORULE", "STATE", "SC", {2025: 60000})
    add_series(db, c, "TST-NORULE", "STATE", "OBC", {2025: 11000})

    # SC student: compared with SC rows; OPEN rows skipped because no verified rule exists
    res = predict(db, inp(quotas=["STATE"], category="SC", air=20000))
    [r] = results(res)
    assert r["category_used"] == "SC"
    assert any("not verified" in e["reason"] for e in res["excluded"])

    # Never compared with another reserved category's rows
    res = predict(db, inp(quotas=["STATE"], category="OBC", air=10500))
    assert {r["category_used"] for r in results(res)} == {"OBC"}

    # With the rule, OPEN becomes a comparison option and the better fit is reported
    set_open_rule(db, "TST-NORULE", "STATE", [2025])
    [r] = results(predict(db, inp(quotas=["STATE"], category="SC", air=5000)))
    assert r["category_used"] in ("OPEN", "SC") and r["historical_fit"] == STRONGER


def test_estimated_rank(db):
    c = make_college(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", YEARS)
    with pytest.raises(PredictorInputError):
        predict(db, inp(rank_type=RankType.estimated, air=None))
    res = predict(db, inp(rank_type=RankType.estimated, air=None, air_low=7000, air_high=9500))
    [r] = results(res)
    assert r["rank_is_estimated"] and "estimated" in r["student_rank_display"]
    assert r["historical_fit"] == POSSIBLE   # conservative end (9500) is not ≤ 9000
    assert r["confidence"] != "higher"
    assert any("ESTIMATED" in c for c in res["caveats"])


@pytest.mark.parametrize("bad", [dict(air=None, state_rank=None), dict(air=-5), dict(quotas=[]),
                                 dict(rank_type=RankType.estimated, air=None, air_low=10, air_high=5),
                                 dict(category="NOT-A-CATEGORY")])
def test_input_validation(db, bad):
    with pytest.raises(PredictorInputError):
        predict(db, inp(**bad))


def test_demo_results_are_flagged(db):
    c = make_college(db)
    add_series(db, c, "MCC", "AIQ", "OPEN", YEARS)
    [r] = results(predict(db, inp()))
    assert r["is_demo"] and any("DEMO" in x for x in r["caveats"])
