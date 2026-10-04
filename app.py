"""
DOST SETUP/iFund Project Financial Monitoring Dashboard
=========================================================
Built for a DOST monitoring officer: quick status, variance, repayment,
appraisal, and an evidence-based narrative — nothing more than that.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import calculations as calc
from narrative import NarrativeContext, generate_monitoring_narrative

load_dotenv()

DATA_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Palette (Section 21 — professional government style: navy/white, status
# colors reserved for meaning, never decorative)
# ---------------------------------------------------------------------------
NAVY = "#1c3f6e"
NAVY_LIGHT = "#2a5b8c"
INK = "#1c2530"
SUB = "#5b6674"
LINE = "#e2e6eb"
GREEN, GREEN_BG = "#1a7f37", "#eaf7ee"
AMBER, AMBER_BG = "#9a6400", "#fdf3df"
RED, RED_BG = "#b42318", "#fdecea"
GRAY, GRAY_BG = "#5b6674", "#eef1f4"

BADGE_STYLE = {
    "ON TRACK": (GREEN, GREEN_BG, "●"),
    "MET": (GREEN, GREEN_BG, "✓"),
    "FOR REVIEW": (AMBER, AMBER_BG, "⚠"),
    "OVERDUE": (RED, RED_BG, "✕"),
    "Above Projection": (GREEN, GREEN_BG, "✓"),
    "Below Projection": (AMBER, AMBER_BG, "⚠"),
    "Insufficient Data": (GRAY, GRAY_BG, "—"),
    "Not Available": (GRAY, GRAY_BG, "—"),
    "No Data Reported": (GRAY, GRAY_BG, "—"),
}


def badge(status: str) -> str:
    color, bg, icon = BADGE_STYLE.get(status, (GRAY, GRAY_BG, "•"))
    return (f'<span style="background:{bg};color:{color};padding:3px 10px;'
            f'border-radius:4px;font-weight:600;font-size:0.85rem;white-space:nowrap;">'
            f'{icon} {status}</span>')


st.set_page_config(
    page_title="DOST SETUP/iFund Monitoring",
    page_icon="📊",
    layout="wide",
)

st.markdown(f"""
<style>
    .block-container {{ padding-top: 1.2rem; max-width: 1280px; }}
    div[data-testid="stMetric"] {{
        background: #ffffff; border: 1px solid {LINE}; border-radius: 8px;
        padding: 12px 16px 8px;
    }}
    div[data-testid="stMetricLabel"] {{ color: {SUB}; }}
    .dost-header {{
        background: {NAVY}; color: white; padding: 18px 24px; border-radius: 8px;
        margin-bottom: 14px;
    }}
    .dost-header h1 {{ margin: 0; font-size: 1.35rem; }}
    .dost-header p {{ margin: 4px 0 0; opacity: 0.85; font-size: 0.85rem; }}
    .status-box {{
        border: 1px solid {LINE}; border-radius: 8px; padding: 16px 20px; background: #fff;
    }}
    .flag-row {{
        display: flex; justify-content: space-between; padding: 6px 0;
        border-bottom: 1px solid {LINE}; font-size: 0.92rem;
    }}
    .flag-row:last-child {{ border-bottom: none; }}
    section[data-testid="stSidebar"] {{ background: #fafbfc; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    projections = pd.read_csv(DATA_DIR / "financial_projections.csv")
    # Mirror the reference fm.py baseline logic: approved annual projections are
    # distributed evenly across 12 months before comparing them to monitoring
    # actuals for each year (Year 1, Year 2, ...).
    projections = calc.build_monthly_baseline(projections)

    return {
        "project_master": pd.read_csv(DATA_DIR / "project_master.csv"),
        "financial_projections": projections,
        "monthly_actuals": pd.read_csv(DATA_DIR / "monthly_actuals.csv"),
        "repayment_records": pd.read_csv(DATA_DIR / "repayment_records.csv"),
        "appraisal": pd.read_csv(DATA_DIR / "appraisal.csv"),
        "risk_objectives": pd.read_csv(DATA_DIR / "risk_objectives.csv"),
        "objective_targets": pd.read_csv(DATA_DIR / "objective_targets.csv"),
    }


data = load_data()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "actuals_overrides" not in st.session_state:
    st.session_state.actuals_overrides = {}  # (cooperator, year, month, line_item) -> value
if "narrative_text" not in st.session_state:
    st.session_state.narrative_text = None
if "narrative_error" not in st.session_state:
    st.session_state.narrative_error = None


def get_working_actuals(cooperator: str, year: int) -> pd.DataFrame:
    """Base simulated actuals with any in-session edits applied on top."""
    df = data["monthly_actuals"].copy()
    for (coop, yr, month, li), val in st.session_state.actuals_overrides.items():
        if coop == cooperator and yr == year:
            mask = (df["cooperator"] == coop) & (df["year"] == yr) & (df["month"] == month) & (df["line_item"] == li)
            df.loc[mask, "actual_value"] = val
    return df


def available_months(cooperator: str, year: int) -> list[int]:
    df = data["monthly_actuals"]
    months = sorted(df[(df["cooperator"] == cooperator) & (df["year"] == year)]["month"].unique().tolist())
    return [int(m) for m in months]


# ---------------------------------------------------------------------------
# Sidebar — Global filters (Section 6: compact, not visually dominant)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("#### Project Selection")
    cooperators = data["project_master"]["cooperator"].tolist()
    cooperator = st.selectbox("Cooperator / MSME", cooperators)

    year_options = sorted(data["financial_projections"]["year"].unique().tolist())
    year_labels = {0: "Year 0 (Baseline)", 1: "Year 1", 2: "Year 2", 3: "Year 3", 4: "Year 4", 5: "Year 5"}
    year = st.selectbox("Project Year", year_options, index=1, format_func=lambda y: year_labels.get(y, f"Year {y}"))

    months = available_months(cooperator, year)
    if months:
        default_period = 6 if 6 in months else months[-1]
        month_range = st.slider(
            "Monitoring Month Range",
            min_value=1,
            max_value=max(months),
            value=(1, default_period),
            format="Month %d",
        )
        start_month, period_month = month_range
        status_label = "Completed (12 of 12 months reported)" if len(months) == 12 \
            else f"In Progress ({len(months)} of 12 months reported)"
        st.caption("This range filters financial KPI charts, variance summaries, repayment records, and narrative evidence.")
    else:
        start_month = None
        period_month = None
        status_label = "No Data Reported"

    st.caption(f"**Monitoring Status:** {status_label}")

    st.markdown("---")
    threshold_pct = st.slider("Review Threshold (%)", min_value=5, max_value=30,
                               value=int(calc.DEFAULT_REVIEW_THRESHOLD_PCT), step=1)
    st.caption("Cumulative variance at or beyond this threshold is flagged for review.")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
pm = data["project_master"][data["project_master"]["cooperator"] == cooperator].iloc[0]
st.markdown(f"""
<div class="dost-header">
  <h1>DOST SETUP / iFund — Financial Project Monitoring</h1>
  <p>{cooperator} · {pm['location']}</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Simulation input (collapsed by default — Section 11: st.data_editor for
# simulation purposes; kept out of the main flow so it never distracts a
# monitoring officer who only wants to read the dashboard)
# ---------------------------------------------------------------------------
if months:
    with st.expander("Simulate monthly actuals (for testing/demo only)", expanded=False):
        st.caption("Pre-filled with the sample simulated actuals. Edit cells or use a quick scenario, "
                   "then the whole dashboard recalculates.")
        qcols = st.columns(4)
        base_year_proj = data["financial_projections"]
        proj_lookup = dict(zip(
            base_year_proj[(base_year_proj.cooperator == cooperator) & (base_year_proj.year == year)]["line_item"],
            base_year_proj[(base_year_proj.cooperator == cooperator) & (base_year_proj.year == year)]["monthly_value"],
        ))

        def apply_scenario(scenario: str):
            for li in calc.LINE_ITEMS:
                base_val = proj_lookup.get(li, 0)
                for m in months:
                    if scenario == "reset":
                        val = base_val
                    elif scenario == "on_track":
                        val = base_val * 1.02
                    elif scenario == "raw_spike" and li == "raw_materials":
                        val = base_val * 1.22
                    elif scenario == "sales_drop" and li == "gross_sales":
                        val = base_val * 0.82
                    else:
                        val = base_val * 1.02
                    st.session_state.actuals_overrides[(cooperator, year, m, li)] = round(val, 2)

        if qcols[0].button("Fill: On track"):
            apply_scenario("on_track"); st.rerun()
        if qcols[1].button("Fill: Raw materials +22%"):
            apply_scenario("raw_spike"); st.rerun()
        if qcols[2].button("Fill: Sales −18%"):
            apply_scenario("sales_drop"); st.rerun()
        if qcols[3].button("Reset to projected"):
            apply_scenario("reset"); st.rerun()

        working = get_working_actuals(cooperator, year)
        pivot = working[(working.cooperator == cooperator) & (working.year == year)].pivot_table(
            index="line_item", columns="month", values="actual_value"
        ).reindex(calc.LINE_ITEMS)
        pivot.index = [calc.LABELS[i] for i in pivot.index]
        pivot.columns = [f"Month {m}" for m in pivot.columns]
        edited = st.data_editor(pivot, use_container_width=True, key="actuals_editor")

        rev_labels = {v: k for k, v in calc.LABELS.items()}
        for label, row in edited.iterrows():
            li = rev_labels[label]
            for col, val in row.items():
                m = int(col.replace("Month ", ""))
                key = (cooperator, year, m, li)
                if pd.notna(val) and st.session_state.actuals_overrides.get(key) != val:
                    st.session_state.actuals_overrides[key] = float(val)

# ---------------------------------------------------------------------------
# Compute (shared across tabs)
# ---------------------------------------------------------------------------
working_actuals = get_working_actuals(cooperator, year)

if months:
    variance_df = calc.compute_variance(
        data["financial_projections"], working_actuals, cooperator, year, max(months), threshold_pct
    )
    period_rows = calc.summarize_variance_range(
        variance_df, start_month, period_month, threshold_pct
    )
    selected_repayments = data["repayment_records"][
        (data["repayment_records"]["month"] >= start_month)
        & (data["repayment_records"]["month"] <= period_month)
    ]
    repayment = calc.compute_repayment(selected_repayments, cooperator, year, period_month)
else:
    start_month = None
    variance_df = pd.DataFrame()
    period_rows = pd.DataFrame()
    repayment = calc.RepaymentSummary(0, 0, 0, None, "Insufficient Data")

appraisal = calc.compute_appraisal(data["appraisal"], working_actuals, cooperator, year, len(months))

flagged_count = int(period_rows["flagged"].sum()) if not period_rows.empty else 0
overall_status, overall_message = calc.overall_monitoring_status(flagged_count, repayment.status) \
    if months else ("No Data Reported", "No monitoring data has been reported for this project year yet.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_overview, tab_variance, tab_repayment, tab_narrative = st.tabs(
    ["Overview", "Actuals & Variance", "Repayment & Appraisal", "Narrative"]
)

# ===========================================================================
# TAB 1 — OVERVIEW
# ===========================================================================
with tab_overview:
    if not months:
        st.info(f"No monitoring data has been reported for {cooperator} in {year_labels.get(year, year)} yet. "
                f"Projected figures remain available for reference in **Actuals & Variance**.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Project Cost", calc.format_php(pm["total_project_cost"], compact=True))
        c2.metric("DOST Fund", calc.format_php(pm["dost_fund"], compact=True))
        c3.metric("Repayment Coverage", f"{repayment.coverage_ratio:.2f}x" if repayment.coverage_ratio is not None else "—")
        c4.metric("Monitoring Status", overall_status)

        st.markdown("###### Monthly Financial Performance")
        st.caption(
            f"Showing Month {start_month}–{period_month}. Each panel compares the approved "
            "monthly baseline with reported actuals and summarizes the selected range."
        )
        for row_start in range(0, len(calc.LINE_ITEMS), 2):
            chart_columns = st.columns(2)
            for column, li_key in zip(chart_columns, calc.LINE_ITEMS[row_start:row_start + 2]):
                metric_row = period_rows[period_rows.line_item == li_key].iloc[0]
                chart_df = variance_df[
                    (variance_df.line_item == li_key)
                    & variance_df.month.between(start_month, period_month)
                ].sort_values("month")
                with column:
                    with st.container(border=True):
                        st.markdown(f"**{calc.LABELS[li_key]}**")
                        kpi_actual, kpi_projected, kpi_variance = st.columns(3)
                        kpi_actual.metric(
                            "Actual",
                            calc.format_php(metric_row.cumulative_actual, compact=True),
                        )
                        kpi_projected.metric(
                            "Projected",
                            calc.format_php(metric_row.cumulative_projected, compact=True),
                        )
                        variance_impact = calc.variance_impact(
                            li_key, metric_row.cumulative_variance_pct
                        )
                        kpi_variance.metric(
                            f"Variance ({variance_impact})",
                            calc.format_pct(metric_row.cumulative_variance_pct),
                            delta=(
                                f"{metric_row.cumulative_variance_pct:+.1f}%"
                                if metric_row.cumulative_variance_pct is not None
                                else None
                            ),
                            delta_color="inverse" if li_key != "gross_sales" else "normal",
                        )

                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=[f"M{m}" for m in chart_df.month],
                            y=chart_df.projected_monthly,
                            mode="lines+markers",
                            name="Projected",
                            line=dict(color=GRAY, width=3),
                            marker=dict(size=7),
                        ))
                        fig.add_trace(go.Scatter(
                            x=[f"M{m}" for m in chart_df.month],
                            y=chart_df.actual_monthly,
                            mode="lines+markers",
                            name="Actual",
                            line=dict(color=NAVY_LIGHT, width=3),
                            marker=dict(size=7),
                        ))
                        fig.update_layout(
                            height=300,
                            margin=dict(t=10, b=10, l=10, r=10),
                            yaxis_title="₱",
                            legend=dict(orientation="h", y=1.1),
                            plot_bgcolor="white",
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"performance_{li_key}")

        col_status, col_flags = st.columns([1, 1])
        with col_status:
            st.markdown("###### Project Status")
            st.markdown(f"""
            <div class="status-box">
              {badge(overall_status)}
              <p style="margin-top:10px;color:{SUB};font-size:0.9rem;">{overall_message}</p>
            </div>
            """, unsafe_allow_html=True)

        with col_flags:
            st.markdown("###### Key Flags")
            rows_sorted = period_rows.copy()
            rows_sorted["abs_var"] = rows_sorted["cumulative_variance_pct"].abs()
            rows_sorted = rows_sorted.sort_values(["flagged", "abs_var"], ascending=[False, False])
            flag_html = '<div class="status-box">'
            for _, r in rows_sorted.iterrows():
                impact = calc.variance_impact(r.line_item, r.cumulative_variance_pct)
                icon = "⚠" if r.flagged else ("✓" if impact != "Unfavorable" else "!")
                color = RED if impact == "Unfavorable" else (GREEN if impact == "Favorable" else AMBER)
                var_txt = calc.format_pct(r.cumulative_variance_pct) if r.has_data or r.cumulative_actual is not None else "No data"
                flag_html += (f'<div class="flag-row"><span>{icon} {r.label}</span>'
                              f'<span style="color:{color};font-weight:600;">{impact} · {var_txt}</span></div>')
            flag_html += (f'<div class="flag-row"><span>{"✓" if repayment.status in ("MET","ON TRACK") else "⚠"} Repayment</span>'
                          f'<span style="font-weight:600;">{repayment.status}</span></div>')
            flag_html += "</div>"
            st.markdown(flag_html, unsafe_allow_html=True)

# ===========================================================================
# TAB 2 — ACTUALS & VARIANCE
# ===========================================================================
with tab_variance:
    if not months:
        st.info("No actuals reported yet for this project year.")
    else:
        st.markdown(f"###### Actual vs Projected — Months {start_month}–{period_month}")
        selected_variance_df = variance_df[
            variance_df.month.between(start_month, period_month)
        ]
        table_rows = []
        for _, r in period_rows.iterrows():
            table_rows.append({
                "Financial Item": r.label,
                "Projected": calc.format_php(r.cumulative_projected),
                "Actual": calc.format_php(r.cumulative_actual) if r.cumulative_actual is not None else "Not Reported",
                "Variance": calc.format_pct(r.cumulative_variance_pct),
                "Impact": calc.variance_impact(r.line_item, r.cumulative_variance_pct),
                "Status": "⚠ For Review" if r.flagged else ("✓ On Track" if r.cumulative_variance_pct is not None else "— No Data"),
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("###### Variance by Financial Item — Selected Range")
            bar_df = period_rows.copy()
            colors = [
                RED if calc.variance_impact(row.line_item, row.cumulative_variance_pct) == "Unfavorable"
                else GREEN if calc.variance_impact(row.line_item, row.cumulative_variance_pct) == "Favorable"
                else GRAY
                for row in bar_df.itertuples()
            ]
            fig = go.Figure(go.Bar(
                x=bar_df.cumulative_variance_pct, y=bar_df.label, orientation="h",
                marker_color=colors,
                text=[calc.format_pct(v) for v in bar_df.cumulative_variance_pct],
                textposition="outside",
            ))
            fig.add_vline(x=threshold_pct, line_dash="dash", line_color=AMBER)
            fig.add_vline(x=-threshold_pct, line_dash="dash", line_color=AMBER)
            fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                               xaxis_title="Selected-Range Variance % (color shows financial impact)",
                               plot_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            st.markdown("###### Monthly Variance Trend")
            fig2 = go.Figure()
            palette = {"gross_sales": NAVY, "raw_materials": RED, "direct_labor": "#6b7684",
                       "mfg_overhead": "#2a5b8c", "operating_expenses": AMBER}
            for li in calc.LINE_ITEMS:
                sub = selected_variance_df[selected_variance_df.line_item == li].sort_values("month")
                fig2.add_trace(go.Scatter(x=sub.month, y=sub.monthly_variance_pct, mode="lines+markers",
                                           name=calc.LABELS[li], line=dict(color=palette[li])))
            fig2.add_hline(y=threshold_pct, line_dash="dash", line_color=AMBER)
            fig2.add_hline(y=-threshold_pct, line_dash="dash", line_color=AMBER)
            fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                                xaxis_title="Month", yaxis_title="Monthly variance %",
                                legend=dict(orientation="h", y=-0.25), plot_bgcolor="white")
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("###### Monthly Actuals")
        wide = selected_variance_df.pivot_table(index="line_item", columns="month", values="actual_monthly").reindex(calc.LINE_ITEMS)
        wide.index = [calc.LABELS[i] for i in wide.index]
        wide.columns = [f"Month {m}" for m in wide.columns]
        display_wide = wide.map(lambda v: calc.format_php(v) if pd.notna(v) else "Not Reported")
        st.dataframe(display_wide, use_container_width=True)

# ===========================================================================
# TAB 3 — REPAYMENT & APPRAISAL
# ===========================================================================
with tab_repayment:
    st.markdown("### Repayment Monitoring")
    if not months:
        st.info("No repayment records reported yet for this project year.")
    else:
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Cumulative Amount Due", calc.format_php(repayment.cumulative_due, compact=True))
        r2.metric("Amount Paid", calc.format_php(repayment.cumulative_paid, compact=True))
        r3.metric("Outstanding Balance", calc.format_php(repayment.outstanding_balance, compact=True))
        r4.metric("Payment Coverage", f"{repayment.coverage_ratio*100:.1f}%" if repayment.coverage_ratio is not None else "—")
        r5.markdown(f"**Repayment Status**<br>{badge(repayment.status)}", unsafe_allow_html=True)

        st.markdown("###### Scheduled vs Actual Payments")
        rep_detail = calc.repayment_detail_table(selected_repayments, cooperator, year)
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=[f"M{m}" for m in rep_detail.month], y=rep_detail.amount_due,
                               name="Scheduled", marker_color=GRAY))
        fig3.add_trace(go.Bar(x=[f"M{m}" for m in rep_detail.month], y=rep_detail.amount_paid,
                               name="Actual", marker_color=NAVY))
        fig3.update_layout(barmode="group", height=320, margin=dict(t=10, b=10, l=10, r=10),
                            yaxis_title="₱", legend=dict(orientation="h", y=1.1), plot_bgcolor="white")
        st.plotly_chart(fig3, use_container_width=True)

        st.markdown("###### Repayment Details")
        detail_display = rep_detail.copy()
        detail_display["Period"] = detail_display["month"].apply(lambda m: f"Month {m}")
        detail_display["Due"] = detail_display["amount_due"].apply(calc.format_php)
        detail_display["Paid"] = detail_display["amount_paid"].apply(calc.format_php)
        detail_display["Difference"] = detail_display["difference"].apply(lambda d: f"{'+' if d>=0 else ''}{calc.format_php(d)}")
        detail_display["Status"] = detail_display["status"].apply(lambda s: "✓" if s == "Met" else "⚠ For Review")
        st.dataframe(detail_display[["Period", "Due", "Paid", "Difference", "Status"]],
                     use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Investment Appraisal")
    a1, a2, a3, a4 = st.columns(4)
    if appraisal.approx_actual_roi is not None:
        a1.metric("Actual ROI (this year)", f"{appraisal.approx_actual_roi*100:.1f}%")
    else:
        a1.metric("Actual ROI (this year)", "—")
        a1.caption("Insufficient Data — requires a full 12 months of actuals.")
    a2.metric("Projected ROI", f"{appraisal.projected_roi*100:.1f}%" if appraisal.projected_roi is not None else "—")
    a3.metric("Projected IRR", f"{appraisal.projected_irr*100:.2f}%" if appraisal.projected_irr is not None else "—")
    a4.metric("Projected NPV", calc.format_php(appraisal.projected_npv, compact=True) if appraisal.projected_npv is not None else "—")
    st.metric("Projected BCR", f"{appraisal.projected_bcr:.2f}" if appraisal.projected_bcr is not None else "—")

    st.markdown("###### Appraisal Summary")
    roi_line = f"ROI: {appraisal.roi_status}" if appraisal.available else "ROI: Insufficient Data (partial year)"
    st.markdown(f"""
    <div class="status-box" style="font-size:0.9rem;">
      {roi_line}<br>
      BCR: {"Positive (above 1.0)" if appraisal.projected_bcr and appraisal.projected_bcr > 1 else "Reference"}<br>
      IRR: Reference (from proposal, not recomputed)<br>
      NPV: Reference (from proposal, not recomputed)
    </div>
    """, unsafe_allow_html=True)
    st.caption("NPV, IRR, and BCR are shown as the proposal's own appraisal figures. They require the full "
               "multi-year cash flow series to compute and are not recalculated from a single year of monitoring data.")

# ===========================================================================
# TAB 4 — NARRATIVE
# ===========================================================================
with tab_narrative:
    st.markdown("### Monitoring Narrative")

    if not months:
        st.info("A narrative requires at least one month of reported actuals for this project year.")
    else:
        def get_api_key() -> str | None:
            try:
                if "GEMINI_API_KEY" in st.secrets:
                    return st.secrets["GEMINI_API_KEY"]
            except Exception:
                pass
            return os.environ.get("GEMINI_API_KEY")

        def build_context() -> NarrativeContext:
            evidence_lines = []
            flagged_items = []
            for _, r in period_rows.iterrows():
                if r.has_data:
                    evidence_lines.append(
                        f"{r.label}: actual {calc.format_php(r.actual_monthly)} vs "
                        f"projected {calc.format_php(r.projected_monthly)} for months "
                        f"{start_month}-{period_month} (variance {calc.format_pct(r.cumulative_variance_pct)}; "
                        f"actual {calc.format_php(r.cumulative_actual)} vs projected "
                        f"{calc.format_php(r.cumulative_projected)})."
                    )
                else:
                    evidence_lines.append(f"{r.label}: no actuals reported for months {start_month}-{period_month}.")
                if r.flagged:
                    flagged_items.append(r.label)

            risk_df = data["risk_objectives"][data["risk_objectives"].cooperator == cooperator]
            documented_factors = []
            for _, r in period_rows[period_rows.flagged].iterrows():
                matches = risk_df[risk_df["related_line_items"].str.split(";").apply(lambda items: r.line_item in items)]
                if matches.empty:
                    documented_factors.append(f"{r.label}: no entry in the approved Risk Management table addresses this line item.")
                else:
                    for _, m in matches.iterrows():
                        documented_factors.append(
                            f'{r.label}: named under objective "{m.objective}" — "{m.risk}" '
                            f'(context only, not asserted as the cause; documented mitigation: "{m.mitigation}").'
                        )

            repayment_line = (
                f"Cumulative amount due {calc.format_php(repayment.cumulative_due)} vs paid "
                f"{calc.format_php(repayment.cumulative_paid)} — coverage "
                f"{repayment.coverage_ratio*100:.1f}% — status {repayment.status}."
            )
            if appraisal.available:
                appraisal_line = (
                    f"Approx. actual ROI {appraisal.approx_actual_roi*100:.1f}% vs projected "
                    f"{appraisal.projected_roi*100:.1f}% — {appraisal.roi_status}."
                )
            else:
                appraisal_line = "Insufficient data for actual ROI this year (requires a full 12 months of actuals)."

            return NarrativeContext(
                cooperator=cooperator, year=year, period_month=period_month,
                evidence_lines=evidence_lines, flagged_items=flagged_items,
                documented_factors=documented_factors, repayment_line=repayment_line,
                appraisal_line=appraisal_line,
            )

        button_label = "Regenerate Narrative" if st.session_state.narrative_text else "Generate Narrative"
        if st.button(button_label, type="primary"):
            st.session_state.narrative_error = None
            api_key = get_api_key()
            with st.spinner("Generating narrative..."):
                try:
                    ctx = build_context()
                    text = generate_monitoring_narrative(
                        cooperator,
                        f"Year {year}, Months {start_month}-{period_month}",
                        ctx,
                        api_key=api_key,
                    )
                    st.session_state.narrative_text = text
                except Exception as e:
                    st.session_state.narrative_error = str(e)
                    st.session_state.narrative_text = None

        if st.session_state.narrative_error:
            st.error("Narrative generation is temporarily unavailable. Please try again.")
            with st.expander("Details"):
                st.caption(st.session_state.narrative_error)

        if st.session_state.narrative_text:
            st.markdown(f"""
            <div class="status-box">
              <div style="white-space:pre-wrap;font-size:0.92rem;line-height:1.6;">{st.session_state.narrative_text}</div>
            </div>
            """, unsafe_allow_html=True)
            st.caption("Generated using Gemini AI")
        elif not st.session_state.narrative_error:
            st.caption("Click **Generate Narrative** to produce an evidence-based summary for the selected period. "
                       "All figures come from the calculations above — the AI model only writes the language.")
