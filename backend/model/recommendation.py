"""Support recommendation generation using Gemini/Gemma.

This module is intended to live in the backend layer so the prompt/model choice
is centralized. It can still be imported by the Streamlit frontend when running
in a single-process deployment.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from config import Config


def generate_support_recommendation(
    *,
    overall_severity: str,
    trend_direction: str,
    top_symptoms: List[Dict[str, Any]],
    model_name: str | None = None,
) -> str:
    """Generate a short, actionable support recommendation.

    Args:
        overall_severity: e.g. Minimal/Mild/Moderate/Severe
        trend_direction: e.g. Improving/Stable/Worsening
        top_symptoms: list of dicts with keys: symptom, average_score, entries_count
        model_name: optional override; defaults to Config.GEMINI_MODEL

    Returns:
        Recommendation text.

    Raises:
        ValueError if API key missing or inputs invalid.
        Exception on API/model errors.
    """
    try:
        import google.generativeai as genai
    except Exception as e:
        raise RuntimeError("Missing dependency: google-generativeai") from e

    # Import prompt builder lazily so Streamlit reruns don't get stuck with
    # a stale module state.
    try:
        import importlib
        import model.prompt_template as prompt_template

        if not hasattr(prompt_template, "build_support_recommendation_prompt"):
            prompt_template = importlib.reload(prompt_template)

        build_prompt = getattr(prompt_template, "build_support_recommendation_prompt", None)
        if build_prompt is None:
            raise RuntimeError(
                "Missing build_support_recommendation_prompt in model.prompt_template. "
                "Restart the Streamlit server to reload updated backend modules."
            )
    except Exception as e:
        raise RuntimeError(f"Failed to load recommendation prompt template: {e}") from e

    if not Config.GOOGLE_API_KEY:
        raise ValueError("Missing GOOGLE_API_KEY")

    if not top_symptoms:
        return "AI recommendation unavailable because there is no symptom data to summarize."

    # Normalize payload (avoid surprises in prompt)
    normalized: List[Dict[str, Any]] = []
    for item in top_symptoms:
        symptom = str(item.get("symptom", "")).strip()
        if not symptom:
            continue
        try:
            avg = float(item.get("average_score", 0.0))
        except Exception:
            avg = 0.0
        try:
            cnt = int(item.get("entries_count", 0))
        except Exception:
            cnt = 0
        normalized.append({"symptom": symptom, "average_score": avg, "entries_count": cnt})

    if not normalized:
        return "AI recommendation unavailable because there is no symptom data to summarize."

    symptoms_json = json.dumps(normalized, ensure_ascii=False)

    prompt = build_prompt(
        symptoms_json=symptoms_json,
        overall_severity=str(overall_severity or "N/A"),
        trend_direction=str(trend_direction or "Stable"),
    )

    genai.configure(api_key=Config.GOOGLE_API_KEY)
    model = genai.GenerativeModel(model_name or Config.GEMINI_MODEL)

    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.3,
            top_p=0.9,
            max_output_tokens=512,
        ),
    )

    return (getattr(resp, "text", None) or "").strip()


def generate_self_support_recommendation(
    *,
    overall_severity: str,
    trend_direction: str,
    top_symptoms: List[Dict[str, Any]],
    model_name: str | None = None,
) -> str:
    """Generate a short, actionable self-support recommendation for the individual.

    This mirrors generate_support_recommendation but uses a self-focused prompt
    (directly addressing the user with safe, non-diagnostic language).
    """
    try:
        import google.generativeai as genai
    except Exception as e:
        raise RuntimeError("Missing dependency: google-generativeai") from e

    try:
        import importlib
        import model.prompt_template as prompt_template

        if not hasattr(prompt_template, "build_self_support_recommendation_prompt"):
            prompt_template = importlib.reload(prompt_template)

        build_prompt = getattr(prompt_template, "build_self_support_recommendation_prompt", None)
        if build_prompt is None:
            raise RuntimeError(
                "Missing build_self_support_recommendation_prompt in model.prompt_template. "
                "Restart the Streamlit server to reload updated backend modules."
            )
    except Exception as e:
        raise RuntimeError(f"Failed to load self-support recommendation prompt template: {e}") from e

    if not Config.GOOGLE_API_KEY:
        raise ValueError("Missing GOOGLE_API_KEY")

    if not top_symptoms:
        return "AI recommendation unavailable because there is no symptom data to summarize."

    normalized: List[Dict[str, Any]] = []
    for item in top_symptoms:
        symptom = str(item.get("symptom", "")).strip()
        if not symptom:
            continue
        try:
            avg = float(item.get("average_score", 0.0))
        except Exception:
            avg = 0.0
        try:
            cnt = int(item.get("entries_count", 0))
        except Exception:
            cnt = 0
        normalized.append({"symptom": symptom, "average_score": avg, "entries_count": cnt})

    if not normalized:
        return "AI recommendation unavailable because there is no symptom data to summarize."

    symptoms_json = json.dumps(normalized, ensure_ascii=False)

    prompt = build_prompt(
        symptoms_json=symptoms_json,
        overall_severity=str(overall_severity or "N/A"),
        trend_direction=str(trend_direction or "Stable"),
    )

    genai.configure(api_key=Config.GOOGLE_API_KEY)
    model = genai.GenerativeModel(model_name or Config.GEMINI_MODEL)

    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.3,
            top_p=0.9,
            max_output_tokens=512,
        ),
    )

    return (getattr(resp, "text", None) or "").strip()
