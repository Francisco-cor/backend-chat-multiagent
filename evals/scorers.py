"""Scorers — Fase 11.3 LLM-as-judge + heuristic.

- keyword_scorer: checks expected_keywords in output (case-insensitive)
- llm_judge: if OPENAI/GEMINI key present, asks LLM to judge 0-1; else fallback to keyword
- aggregate: pass if score >= 0.6
"""
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def keyword_scorer(output: str, expected_keywords: List[str]) -> float:
    if not expected_keywords:
        return 1.0
    out = output.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in out)
    return hits / len(expected_keywords)


async def llm_as_judge_scorer(prompt: str, output: str, expected_keywords: List[str]) -> float:
    """LLM-as-judge: asks model to rate 0-1 whether output satisfies prompt.
    Fallback to keyword if no API key or failure.
    """
    # Check if we can call LLM
    try:
        from app.core.config import settings
        # Prefer OpenAI if key present
        if settings.OPENAI_API_KEY:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            judge_prompt = (
                f"Prompt: {prompt}\nExpected keywords: {expected_keywords}\n"
                f"Output: {output}\n\n"
                "Rate 0-1 whether output satisfies prompt and contains expected keywords. "
                "Return only a float like 0.8"
            )
            resp = await client.responses.create(
                model="gpt-5.4-mini", input=[{"role": "user", "content": judge_prompt}]
            )
            text = getattr(resp, "output_text", "") or str(resp)
            # extract float
            m = re.search(r"0?\.\d+|1\.0|1|0", text)
            if m:
                return max(0.0, min(1.0, float(m.group())))
        elif settings.GOOGLE_API_KEY:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=settings.GOOGLE_API_KEY)
            judge_prompt = (
                f"Prompt: {prompt}\nExpected keywords: {expected_keywords}\n"
                f"Output: {output}\nRate 0-1 whether output satisfies prompt. Return float only."
            )
            def _call():
                return client.models.generate_content(
                    model="gemini-3-flash",
                    contents=[types.Content(role="user", parts=[types.Part.from_text(text=judge_prompt)])],
                )
            import asyncio
            resp = await asyncio.to_thread(_call)
            text = getattr(resp, "text", "") or ""
            m = re.search(r"0?\.\d+|1\.0|1|0", text)
            if m:
                return max(0.0, min(1.0, float(m.group())))
    except Exception as e:
        logger.warning(f"LLM judge failed, fallback keyword: {e}")
    return keyword_scorer(output, expected_keywords)


def passes(score: float, threshold: float = 0.6) -> bool:
    return score >= threshold


def score_case(output: str, case: Dict[str, Any]) -> Dict[str, Any]:
    expected = case.get("expected_keywords", [])
    kw_score = keyword_scorer(output, expected)
    return {
        "keyword_score": kw_score,
        "passed": passes(kw_score),
        "expected_keywords": expected,
    }
