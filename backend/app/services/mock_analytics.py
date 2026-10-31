"""Mock-test analytics. Mock scores are never presented as official NEET results."""
from collections import Counter
from statistics import mean

from app.models import MockTest

SUBJECTS = ("Physics", "Chemistry", "Biology")
NOTICE = ("Mock-test scores come from your test provider, not NTA. They are not official NEET "
          "results and different providers' tests are not equally difficult.")


def _pct(score: float, max_score: float) -> float:
    return round(100 * score / max_score, 1) if max_score else 0.0


def analyse(tests: list[MockTest]) -> dict:
    tests = sorted(tests, key=lambda t: (t.test_date, t.id))
    if not tests:
        return {"notice": NOTICE, "count": 0, "history": [], "subjects": {}, "priorities": [],
                "estimate": None}

    history = [{
        "id": t.id, "name": t.name, "provider": t.provider, "test_date": t.test_date.isoformat(),
        "total_score": t.total_score, "max_score": t.max_score,
        "percent": _pct(t.total_score, t.max_score),
        "subjects": {s.subject: _pct(s.score, s.max_score) for s in t.subjects},
    } for t in tests]
    percents = [h["percent"] for h in history]

    # Recent vs earlier: last 3 tests vs everything before them.
    recent, earlier = percents[-3:], percents[:-3]
    trend = None
    if earlier:
        delta = round(mean(recent) - mean(earlier), 1)
        trend = {"recent_avg_percent": round(mean(recent), 1), "earlier_avg_percent": round(mean(earlier), 1),
                 "change_points": delta,
                 "direction": "improving" if delta > 2 else "declining" if delta < -2 else "steady"}

    subjects = {}
    for subj in SUBJECTS:
        vals = [h["subjects"][subj] for h in history if subj in h["subjects"]]
        if vals:
            subjects[subj] = {"average_percent": round(mean(vals), 1), "latest_percent": vals[-1],
                              "best_percent": max(vals), "tests": len(vals)}

    topic_counts = Counter(
        topic.strip() for t in tests for s in t.subjects for topic in (s.weak_topics or []) if topic.strip())

    priorities = []
    if subjects:
        weakest = sorted(subjects.items(), key=lambda kv: kv[1]["average_percent"])
        for subj, stats in weakest[:2]:
            priorities.append(f"{subj}: averaging {stats['average_percent']}% — schedule focused revision "
                              "and timed practice sets.")
    for topic, n in topic_counts.most_common(5):
        priorities.append(f"Revisit '{topic}' (flagged in {n} test{'s' if n > 1 else ''}).")

    # Estimated performance: a band from recent tests, never a single precise number.
    estimate = None
    if len(tests) >= 3:
        last = [t.total_score / t.max_score * 720 for t in tests[-5:]]
        estimate = {
            "label": "Estimate only — not an official or predicted NEET score",
            "score_band_out_of_720": [int(min(last) // 10 * 10), int(-(-max(last) // 10) * 10)],
            "assumptions": [
                "Based on your last {} mock tests, scaled to 720.".format(len(last)),
                "Assumes the mock tests resemble the real paper in difficulty — this often isn't true.",
                "Exam-day conditions, paper difficulty and normalisation can move scores substantially.",
            ],
        }

    return {
        "notice": NOTICE, "count": len(tests), "history": history,
        "best_percent": max(percents), "latest_percent": percents[-1],
        "average_percent": round(mean(percents), 1),
        "trend": trend, "subjects": subjects, "weak_topics": topic_counts.most_common(10),
        "priorities": priorities, "estimate": estimate,
    }
