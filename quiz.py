import json
import os
import random
from typing import List, Dict, Any, Optional

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "questions_uae.json")


def _load_bank() -> List[Dict[str, Any]]:
    if not os.path.exists(_DATA_PATH):
        raise FileNotFoundError(f"Question bank not found at {_DATA_PATH}")
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # basic validation
    for q in data:
        assert "id" in q and "question" in q and "options" in q and "answer" in q
    return data


def get_random_questions(count: int = 10, seed: Optional[str] = None) -> List[Dict[str, Any]]:
    bank = _load_bank()
    rng = random.Random(str(seed) if seed is not None else None)
    picked = rng.sample(bank, k=min(count, len(bank)))
    # Return minimal fields used by UI and grading
    return [
        {
            "id": q["id"],
            "question": q["question"],
            "options": q["options"],
            "answer": q["answer"],
        }
        for q in picked
    ]


def grade_answers(questions: List[Dict[str, Any]], chosen_indices: List[Optional[int]]):
    total = len(questions)
    correct = 0
    for q, c in zip(questions, chosen_indices):
        if c is not None and c == q["answer"]:
            correct += 1
    score = round((correct / total) * 100, 2) if total else 0.0
    return {"total": total, "correct": correct, "score": score}
