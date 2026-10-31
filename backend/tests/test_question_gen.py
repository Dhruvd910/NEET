"""AI question generation pipeline, with fake model responses (no network, no cost)."""
import json
import random
import uuid

from sqlalchemy import select

from app.models import Question, SyllabusChapter
from app.services import question_gen
from app.services.question_gen import AR_OPTIONS, _clean, generate_batch


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}], "usage": {"cost": 0.0001}}


def draft(stem, options, answer, fmt="single"):
    return {"format": fmt, "topic": "t", "difficulty": "easy", "stem": stem, "options": options,
            "answer": answer, "explanation": "because"}


class FakeModels:
    """Writer returns the given drafts; checker answers from a lookup of stem -> option text."""

    def __init__(self, drafts, checker_answers):
        self.drafts, self.checker_answers = drafts, checker_answers

    def post(self, url, json=None):
        prompt = json["messages"][0]["content"]
        if json["response_format"]["json_schema"]["name"] == "neet_questions":
            return Resp({"questions": self.drafts})
        stem = next(s for s in self.checker_answers if s in prompt)
        opts = [line.split(". ", 1)[1] for line in prompt.splitlines() if line[:2] in ("1.", "2.", "3.", "4.")]
        return Resp({"answer": opts.index(self.checker_answers[stem]) + 1, "confident": True, "unambiguous": True,
                     "in_syllabus": True, "issue": ""})


def test_clean_shuffles_and_keeps_the_right_answer():
    rng = random.Random(3)
    q, why = _clean(draft("Q?", ["w", "x", "y", "z"], 3), rng)
    assert not why and q["options"][q["correct_index"]] == "y" and sorted(q["options"]) == ["w", "x", "y", "z"]
    assert _clean(draft("Q?", ["a", "a", "b", "c"], 1), rng)[1] == "duplicate or empty options"
    assert _clean(draft("Q?", ["a", "b", "c", "None of the above"], 1), rng)[1] == "all/none of the above"
    assert _clean(draft("Q?", ["a", "b", "c"], 1), rng)[1] == "malformed"


def test_assertion_reason_options_are_normalised_to_standard_order():
    shuffled = [AR_OPTIONS[2], AR_OPTIONS[0], AR_OPTIONS[3], AR_OPTIONS[1]]
    q, _ = _clean(draft("Assertion (A): x\nReason (R): y", shuffled, 4, "assertion_reason"), random.Random(1))
    assert q["options"] == AR_OPTIONS and q["correct_index"] == 1  # "...NOT the correct explanation"


def test_only_questions_the_checker_agrees_with_are_kept(db):
    ch = db.scalar(select(SyllabusChapter).where(SyllabusChapter.code == "PHY-11-05"))
    tag = uuid.uuid4().hex[:6]
    good, bad = f"Work done by a constant force {tag}?", f"Power is the rate of {tag}?"
    match = f"Match List-I with List-II {tag}\nA. a | I. i"
    fake = FakeModels(
        [draft(good, ["Fd cos θ", "F/d", "Fd²", "zero"], 1),
         draft(bad, ["energy", "momentum", "force", "mass"], 2),  # wrong key: checker says "energy"
         draft(match, ["A-I, B-II, C-III, D-IV", "A-II, B-I, C-IV, D-III", "A-III, B-IV, C-I, D-II", "A-IV, B-III, C-II, D-I"], 1,
               "match")],
        {good: "Fd cos θ", bad: "energy", match: "A-I, B-II, C-III, D-IV"})
    res = generate_batch(db, ch, 3, rng=random.Random(5), client=fake)
    assert (res.drafted, res.kept) == (3, 1)
    assert "checker disagreed with the answer key" in res.rejected and "match answer in list order" in res.rejected
    q = db.scalar(select(Question).where(Question.stem == good))
    assert q.review_status == "ai_checked" and q.options[q.correct_index] == "Fd cos θ" and q.checked_by

    again = generate_batch(db, ch, 1, rng=random.Random(5), client=FakeModels([draft(good, ["Fd cos θ", "F/d", "Fd²", "zero"], 1)],
                                                                           {good: "Fd cos θ"}))
    assert again.kept == 0 and again.rejected == ["near-duplicate"]


def test_generation_is_off_without_a_key():
    assert not question_gen.enabled()
    assert question_gen.start_top_up({"Physics": 10}) is False
