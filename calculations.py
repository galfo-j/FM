"""
Financial calculation logic for the DOST SETUP/iFund monitoring dashboard.

This module performs ALL numeric work: monthly and cumulative variance,
review-threshold flagging, repayment coverage, and investment appraisal
checks. The narrative module (Gemini) never calculates anything — it only
receives the verified results this module produces.

Design principles carried over from the reference HTML simulation:
  - Variance, Repayment, and Appraisal are kept as separate, transparent
    statuses. No composite "financial health score" is created.
  - Missing data is never silently treated as zero, unpaid, or failed.
  - ROI is only approximated once a full 12 months of actuals exist for
    the year; NPV/IRR/BCR are shown as the proposal's own reference
    figures rather than recomputed from partial monitoring data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

LINE_ITEMS = ["gross_sales", "raw_materials", "direct_labor", "mfg_overhead", "operating_expenses"]

LABELS = {
    "gross_sales": "Gross Sales",
    "raw_materials": "Raw Materials",
    "direct_labor": "Direct Labor",
    "mfg_overhead": "Manufacturing Overhead",
    "operating_expenses": "Operating Expenses",
}

DEFAULT_REVIEW_THRESHOLD_PCT = 15.0


def build_monthly_baseline(projections: pd.DataFrame) -> pd.DataFrame:
    """Create the approved monthly monitoring baseline from the annual proposal.

    The reference dashboard (fm.py) treats the approved project projection as a
    yearly figure and then spreads it evenly across 12 months. This function
    makes that baseline construction explicit so the monitoring variance is
    always compared against a monthly baseline, even when the source data only
    contains annual values.
    """
    df = projections.copy()
    if "annual_value" not in df.columns:
        return df

    df["monthly_value"] = pd.to_numeric(df.get("monthly_value", 0), errors="coerce")
    annual = pd.to_numeric(df["annual_value"], errors="coerce")
    df["monthly_value"] = df["monthly_value"].fillna(annual / 12.0)
    return df


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_php(value: Optional[float], compact: bool = False) -> str:
    """Format a peso amount. Returns 'Not Available' for missing values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Not Available"
    if compact:
        abs_v = abs(value)
        if abs_v >= 1_000_000:
            return f"₱{value / 1_000_000:.2f}M"
        if abs_v >= 1_000:
            return f"₱{value / 1_000:.0f}K"
        return f"₱{value:,.0f}"
    return f"₱{value:,.0f}"


def format_pct(value: Optional[float], signed: bool = True) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    sign = "+" if (signed and value >= 0) else ""
    return f"{sign}{value:.1f}%"


def variance_impact(line_item: str, variance_pct: Optional[float]) -> str:
    """Classify variance direction by financial impact, not numeric sign alone.

    Higher gross sales are favorable; higher costs and expenses are
    unfavorable. Lower values have the opposite interpretation.
    """
    if variance_pct is None or pd.isna(variance_pct):
        return "Insufficient Data"
    if line_item not in LINE_ITEMS:
        raise ValueError(f"Unknown financial line item: {line_item}")
    if variance_pct == 0:
        return "On Projection"
    favorable = (
        (line_item == "gross_sales" and variance_pct > 0)
        or (line_item != "gross_sales" and variance_pct < 0)
    )
    return "Favorable" if favorable else "Unfavorable"


# ---------------------------------------------------------------------------
# Variance calculations (Section 8-9 of spec)
# ---------------------------------------------------------------------------

@dataclass
class VarianceRow:
    line_item: str
    label: str
    month: int
    projected_monthly: float
    actual_monthly: Optional[float]
    monthly_variance_pct: Optional[float]
    cumulative_projected: float
    cumulative_actual: Optional[float]
    cumulative_variance_pct: Optional[float]
    flagged: bool
    has_data: bool


def compute_variance(
    projections: pd.DataFrame,
    actuals: pd.DataFrame,
    cooperator: str,
    year: int,
    reported_months: int,
    threshold_pct: float = DEFAULT_REVIEW_THRESHOLD_PCT,
) -> pd.DataFrame:
    """
    Computes monthly and cumulative variance for each of the five monitored
    line items, for months 1..reported_months.

    Handles missing months gracefully: a month with no actual entry is
    excluded from the actual sum, and cumulative variance is computed only
    from months that actually have data (never treated as zero).
    """
    proj = projections[(projections["cooperator"] == cooperator) & (projections["year"] == year)]
    proj_monthly = dict(zip(proj["line_item"], proj["monthly_value"]))

    act = actuals[(actuals["cooperator"] == cooperator) & (actuals["year"] == year)]

    rows: list[VarianceRow] = []
    cum_actual = {li: 0.0 for li in LINE_ITEMS}
    cum_projected = {li: 0.0 for li in LINE_ITEMS}
    cum_has_any_data = {li: False for li in LINE_ITEMS}

    for m in range(1, reported_months + 1):
        for li in LINE_ITEMS:
            projected_m = proj_monthly.get(li)
            actual_row = act[(act["month"] == m) & (act["line_item"] == li)]
            has_data = not actual_row.empty and pd.notna(actual_row["actual_value"].iloc[0])
            actual_m = float(actual_row["actual_value"].iloc[0]) if has_data else None

            monthly_var = None
            if has_data and projected_m:
                monthly_var = (actual_m - projected_m) / projected_m * 100

            cum_projected[li] += projected_m or 0
            if has_data:
                cum_actual[li] += actual_m
                cum_has_any_data[li] = True

            cum_var = None
            flagged = False
            if cum_has_any_data[li] and cum_projected[li]:
                cum_var = (cum_actual[li] - cum_projected[li]) / cum_projected[li] * 100
                flagged = abs(cum_var) >= threshold_pct

            rows.append(VarianceRow(
                line_item=li, label=LABELS[li], month=m,
                projected_monthly=projected_m or 0, actual_monthly=actual_m,
                monthly_variance_pct=monthly_var,
                cumulative_projected=cum_projected[li],
                cumulative_actual=cum_actual[li] if cum_has_any_data[li] else None,
                cumulative_variance_pct=cum_var,
                flagged=flagged, has_data=has_data,
            ))

    return pd.DataFrame([r.__dict__ for r in rows])


def get_variance_status(cumulative_variance_pct: Optional[float], threshold_pct: float) -> str:
    """Transparent status helper — Section 29 of spec."""
    if cumulative_variance_pct is None:
        return "Insufficient Data"
    return "FOR REVIEW" if abs(cumulative_variance_pct) >= threshold_pct else "ON TRACK"


def latest_period_summary(variance_df: pd.DataFrame, period_month: int) -> pd.DataFrame:
    """Returns one row per line item reflecting cumulative status as of period_month."""
    return variance_df[variance_df["month"] == period_month].reset_index(drop=True)


def summarize_variance_range(
    variance_df: pd.DataFrame,
    start_month: int,
    end_month: int,
    threshold_pct: float = DEFAULT_REVIEW_THRESHOLD_PCT,
) -> pd.DataFrame:
    """Summarize actual and projected values over an inclusive month range.

    The projected denominator includes only months with reported actuals, so
    missing values are not treated as zero-performance months.
    """
    if start_month < 1 or end_month < start_month:
        raise ValueError("The month range must start at 1 or later and end on or after its start.")

    selected = variance_df[
        variance_df["month"].between(start_month, end_month)
    ]
    summaries: list[dict[str, object]] = []
    for line_item in LINE_ITEMS:
        item = selected[selected["line_item"] == line_item]
        reported = item[item["actual_monthly"].notna()]
        has_data = not reported.empty
        projected = float(reported["projected_monthly"].sum()) if has_data else 0.0
        actual = float(reported["actual_monthly"].sum()) if has_data else None
        variance = (
            (actual - projected) / projected * 100
            if has_data and projected
            else None
        )
        summaries.append({
            "line_item": line_item,
            "label": LABELS[line_item],
            "month": end_month,
            "projected_monthly": projected,
            "actual_monthly": actual,
            "monthly_variance_pct": variance,
            "cumulative_projected": projected,
            "cumulative_actual": actual,
            "cumulative_variance_pct": variance,
            "flagged": variance is not None and abs(variance) >= threshold_pct,
            "has_data": has_data,
        })

    return pd.DataFrame(summaries)


# ---------------------------------------------------------------------------
# Repayment calculations (Section 13-15 of spec)
# ---------------------------------------------------------------------------

@dataclass
class RepaymentSummary:
    cumulative_due: float
    cumulative_paid: float
    outstanding_balance: float
    coverage_ratio: Optional[float]
    status: str


def compute_repayment(
    repayment_records: pd.DataFrame,
    cooperator: str,
    year: int,
    period_month: int,
) -> RepaymentSummary:
    """
    Computes cumulative repayment status through period_month.
    Status logic (Section 29):
        Paid >= Due  -> MET
        Paid < Due   -> FOR REVIEW
    (OVERDUE is reserved for cases where payment data explicitly confirms
    a missed period beyond a grace allowance — not inferred here from
    partial shortfalls alone.)
    """
    rec = repayment_records[
        (repayment_records["cooperator"] == cooperator)
        & (repayment_records["year"] == year)
        & (repayment_records["month"] <= period_month)
    ]

    if rec.empty:
        return RepaymentSummary(0, 0, 0, None, "Insufficient Data")

    cumulative_due = float(rec["amount_due"].sum())
    cumulative_paid = float(rec["amount_paid"].sum())
    outstanding = max(cumulative_due - cumulative_paid, 0)
    coverage = (cumulative_paid / cumulative_due) if cumulative_due else None

    if cumulative_due == 0:
        status = "Insufficient Data"
    elif cumulative_paid >= cumulative_due:
        status = "MET"
    elif coverage is not None and coverage >= 0.95:
        status = "ON TRACK"
    else:
        status = "FOR REVIEW"

    return RepaymentSummary(cumulative_due, cumulative_paid, outstanding, coverage, status)


def repayment_detail_table(repayment_records: pd.DataFrame, cooperator: str, year: int) -> pd.DataFrame:
    rec = repayment_records[
        (repayment_records["cooperator"] == cooperator) & (repayment_records["year"] == year)
    ].copy()
    rec["difference"] = rec["amount_paid"] - rec["amount_due"]
    rec["status"] = rec["difference"].apply(lambda d: "Met" if d >= 0 else "For Review")
    return rec.sort_values("month").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Investment appraisal (Section 16-17 of spec)
# ---------------------------------------------------------------------------

@dataclass
class AppraisalResult:
    available: bool
    approx_actual_profit: Optional[float] = None
    approx_actual_roi: Optional[float] = None
    projected_roi: Optional[float] = None
    projected_irr: Optional[float] = None
    projected_npv: Optional[float] = None
    projected_bcr: Optional[float] = None
    total_investment: Optional[float] = None
    roi_status: str = "Insufficient Data"


def compute_appraisal(
    appraisal_data: pd.DataFrame,
    actuals: pd.DataFrame,
    cooperator: str,
    year: int,
    reported_months: int,
) -> AppraisalResult:
    """
    Actual ROI is only computed when a FULL 12 months of actuals exist for
    the year (all five line items, all twelve months present). Otherwise
    returns available=False so the UI can show "Insufficient Data" rather
    than a misleading partial-year figure.
    NPV / IRR / BCR are never recomputed from monitoring data — they are
    passed through as the proposal's own projected reference figures.
    """
    app_row = appraisal_data[appraisal_data["cooperator"] == cooperator]
    if app_row.empty:
        return AppraisalResult(available=False)
    app_row = app_row.iloc[0]

    projected_roi = float(app_row["projected_roi"])
    projected_irr = float(app_row["projected_irr"])
    projected_npv = float(app_row["projected_npv_0pct"])
    projected_bcr = float(app_row["projected_bcr"])
    total_investment = float(app_row["total_investment"])

    if reported_months < 12:
        return AppraisalResult(
            available=False,
            projected_roi=projected_roi, projected_irr=projected_irr,
            projected_npv=projected_npv, projected_bcr=projected_bcr,
            total_investment=total_investment,
        )

    act = actuals[(actuals["cooperator"] == cooperator) & (actuals["year"] == year)]
    pivot = act.pivot_table(index="month", columns="line_item", values="actual_value")
    # Require complete data across all 12 months and all 5 line items.
    if pivot.shape[0] < 12 or not set(LINE_ITEMS).issubset(pivot.columns) or pivot[LINE_ITEMS].isna().any().any():
        return AppraisalResult(
            available=False,
            projected_roi=projected_roi, projected_irr=projected_irr,
            projected_npv=projected_npv, projected_bcr=projected_bcr,
            total_investment=total_investment,
        )

    approx_profit = float(
        (pivot["gross_sales"] - pivot["raw_materials"] - pivot["direct_labor"]
         - pivot["mfg_overhead"] - pivot["operating_expenses"]).sum()
    )
    approx_roi = approx_profit / total_investment if total_investment else None
    roi_status = "Above Projection" if (approx_roi is not None and approx_roi >= projected_roi) else "Below Projection"

    return AppraisalResult(
        available=True,
        approx_actual_profit=approx_profit,
        approx_actual_roi=approx_roi,
        projected_roi=projected_roi, projected_irr=projected_irr,
        projected_npv=projected_npv, projected_bcr=projected_bcr,
        total_investment=total_investment,
        roi_status=roi_status,
    )


# ---------------------------------------------------------------------------
# Overall (non-composite) monitoring status — Section 27
# ---------------------------------------------------------------------------

def overall_monitoring_status(flagged_count: int, repayment_status: str) -> tuple[str, str]:
    """
    Returns (status_label, status_message). This is a simple, transparent
    summary of the two independent checks — NOT a composite score.
    """
    variance_ok = flagged_count == 0
    repayment_ok = repayment_status in ("MET", "ON TRACK")

    if variance_ok and repayment_ok:
        return "ON TRACK", "Financial performance is within the review threshold and repayment coverage is currently sufficient."
    issues = []
    if not variance_ok:
        issues.append(f"{flagged_count} line item(s) exceeded the review threshold")
    if not repayment_ok:
        issues.append("repayment coverage is below the amount due")
    return "FOR REVIEW", "; ".join(issues).capitalize() + "."
