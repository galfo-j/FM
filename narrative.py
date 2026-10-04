"""
Narrative generation for the DOST SETUP/iFund monitoring dashboard.

IMPORTANT: This module NEVER performs financial calculations and NEVER
determines monitoring status. It only turns already-verified numbers
(produced by utils.calculations) into a short, bounded, four-part
narrative using the Gemini API. If the API is unavailable, the caller
is expected to keep showing all dashboard figures and simply omit the
narrative — this module never fabricates one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

SYSTEM_PROMPT = """You are assisting a DOST SETUP/iFund monitoring officer.

Generate a concise monitoring narrative using ONLY the verified project information provided.

Do not invent figures, causes, risks, predictions, or recommendations.

Use exactly these four sections, in this order, with these exact headers:

EVIDENCE:
OBSERVATION:
POSSIBLE CONTRIBUTING FACTORS:
QUESTION FOR REVIEW:

Evidence and Observation must be based only on the provided monitoring results.

Possible Contributing Factors may ONLY use documented factors from the approved project records or
risk-management information provided below. If no documented contributing factor is available for a
flagged item, state this clearly instead of guessing.

The Question for Review should be a concise monitoring question based on the identified issue or
variance, addressed to the cooperator/MSME.

Keep the output professional, factual, concise, and suitable for display in a government monitoring
dashboard. Do not predict future business performance. Do not diagnose causes without evidence. Do not
label the MSME as financially unhealthy. Do not create unsupported risk assessments."""


@dataclass
class NarrativeContext:
    cooperator: str
    year: int
    period_month: int
    evidence_lines: list[str]
    flagged_items: list[str]
    documented_factors: list[str]
    repayment_line: str
    appraisal_line: str


def build_context_text(ctx: NarrativeContext) -> str:
    """Serializes the verified monitoring context into plain text for the model."""
    lines = [
        f"Cooperator: {ctx.cooperator}",
        f"Reporting period: Year {ctx.year}, Month {ctx.period_month}",
        "",
        "VERIFIED EVIDENCE (calculated by the monitoring system, not by you):",
    ]
    lines.extend(f"  - {line}" for line in ctx.evidence_lines)
    lines.append("")
    if ctx.flagged_items:
        lines.append(f"Line item(s) that crossed the review threshold this period: {', '.join(ctx.flagged_items)}")
    else:
        lines.append("No line item crossed the review threshold this period.")
    lines.append("")
    lines.append("DOCUMENTED FACTORS FROM THE APPROVED PROJECT RECORDS (use ONLY these, nothing else):")
    if ctx.documented_factors:
        lines.extend(f"  - {f}" for f in ctx.documented_factors)
    else:
        lines.append("  - No documented contributing factor is available in the provided project records.")
    lines.append("")
    lines.append(f"Repayment status: {ctx.repayment_line}")
    lines.append(f"Appraisal status: {ctx.appraisal_line}")
    return "\n".join(lines)


def generate_monitoring_narrative(
    project: str,
    period: str,
    context: NarrativeContext,
    api_key: Optional[str] = None,
    model: str = "gemini-2.0-flash",
) -> str:
    """
    Calls the Gemini API to turn the verified context into a four-part
    narrative. Raises an exception on any failure (missing key, network
    error, quota, timeout, empty response) — the caller is responsible
    for catching this and showing a graceful error message without
    fabricating a narrative.
    """
    from google import genai
    from google.genai import types

    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("No Gemini API key configured.")

    client = genai.Client(api_key=key)
    context_text = build_context_text(context)
    full_prompt = f"{SYSTEM_PROMPT}\n\n---\n\nVERIFIED MONITORING CONTEXT:\n\n{context_text}"

    response = client.models.generate_content(
        model=model,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=700,
        ),
    )

    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise RuntimeError("Gemini returned an empty response.")
    return text.strip()
