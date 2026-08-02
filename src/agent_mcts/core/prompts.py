"""Prompt construction for node expansions.

Root children get "attempt the task, differently from your siblings" prompts;
deeper children get "revise your work given this evaluation feedback" prompts
(their forked session already contains the full attempt history).
"""

from __future__ import annotations

_MAX_DETAIL_CHARS = 3000
_MAX_SUMMARY_CHARS = 300


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def _diversity_block(sibling_summaries: list[str], intro: str) -> str:
    summaries = [s for s in sibling_summaries if s.strip()]
    if not summaries:
        return ""
    lines = "\n".join(f"- {_clip(s, _MAX_SUMMARY_CHARS)}" for s in summaries)
    return f"\n{intro}\n{lines}\nTake a meaningfully different approach from all of the above.\n"


def root_attempt_prompt(task: str, baseline_detail: str, sibling_summaries: list[str]) -> str:
    baseline = ""
    if baseline_detail.strip():
        baseline = (
            "\nBaseline evaluation of the untouched repository:\n"
            f"{_clip(baseline_detail, _MAX_DETAIL_CHARS)}\n"
        )
    diversity = _diversity_block(
        sibling_summaries, "Sibling attempts in this search already took these approaches:"
    )
    return (
        "You are one attempt in a tree search over solutions to a coding task.\n"
        f"\nTASK:\n{task}\n"
        f"{baseline}{diversity}\n"
        "Work in the current directory and implement a complete solution attempt. "
        "Do not commit; leave your changes in the working tree. "
        "End with a 1-3 sentence summary of the approach you took."
    )


def revision_prompt(
    task: str, parent_reward: float, eval_detail: str, sibling_summaries: list[str]
) -> str:
    feedback = ""
    if eval_detail.strip():
        feedback = f"\nEvaluation feedback:\n{_clip(eval_detail, _MAX_DETAIL_CHARS)}\n"
    diversity = _diversity_block(
        sibling_summaries, "Other revisions of this same attempt already tried:"
    )
    return (
        f"Your previous attempt at the task below scored {parent_reward:.2f} "
        "on the evaluation (0 = worst, 1 = best).\n"
        f"\nTASK:\n{task}\n"
        f"{feedback}{diversity}\n"
        "Revise your work in the current directory to address the problems shown in the "
        "feedback. Do not commit; leave your changes in the working tree. "
        "End with a 1-3 sentence summary of what you changed."
    )
