"""
Generates the sample CSV data files used by the dashboard.

Baseline / projected figures (project master data, financial projections,
appraisal figures, risk-management entries) are transcribed directly from
the uploaded SETUP/iFund project proposal (SJL Corporation, 2024) and are
NOT invented.

Monthly actuals and repayment records are SIMULATED for demonstration and
testing purposes only, built around the proposal's own projected figures,
with an intentional mix of on-track, minor-variance, and significant-variance
months, plus a mix of fully-paid and insufficient repayment periods.

Run once with `python generate_sample_data.py` to (re)produce the CSVs.
"""

import pandas as pd

COOPERATOR = "SJL Corporation"

# ---------------------------------------------------------------------------
# 1. PROJECT MASTER DATA  (from the proposal's Financial Aspect section)
# ---------------------------------------------------------------------------
project_master = pd.DataFrame([{
    "cooperator": COOPERATOR,
    "location": "Molo, Iloilo City",
    "source_document": "SJL_2ProjectProposal.pdf",
    "total_project_cost": 19_209_600,
    "dost_fund": 4_881_600,
    "dost_fund_pct": 0.25,
    "proponent_equity": 14_328_000,
    "monthly_amortization": 81_360,
    "sales_growth_assumption": 0.30,
    "cogs_opex_growth_assumption": 0.12,
    "employment_target": 1,
    "project_start_year": 2025,
}])
project_master.to_csv("project_master.csv", index=False)

# ---------------------------------------------------------------------------
# 2. FINANCIAL PROJECTIONS  (annual, from the proposal's Projected Income
#    Statement and Projected Cash Flow tables — five monitored line items)
# ---------------------------------------------------------------------------
# gross_sales -> Projected Income Statement
# raw_materials / direct_labor / mfg_overhead / operating_expenses -> Projected Cash Flow
annual_projections = {
    0: {"gross_sales": 35_502_000, "raw_materials": 14_097_600, "direct_labor": 4_680_000,
        "mfg_overhead": 3_107_275.20, "operating_expenses": 7_616_170.80},
    1: {"gross_sales": 46_152_600, "raw_materials": 15_664_000, "direct_labor": 5_200_000,
        "mfg_overhead": 3_452_528, "operating_expenses": 8_462_412},
    2: {"gross_sales": 53_075_490, "raw_materials": 18_796_800, "direct_labor": 6_240_000,
        "mfg_overhead": 4_143_034, "operating_expenses": 10_154_894},
    3: {"gross_sales": 61_036_814, "raw_materials": 22_556_160, "direct_labor": 7_488_000,
        "mfg_overhead": 4_971_640, "operating_expenses": 12_185_873},
    4: {"gross_sales": 70_192_336, "raw_materials": 27_067_392, "direct_labor": 8_985_600,
        "mfg_overhead": 5_965_968, "operating_expenses": 14_623_048},
    5: {"gross_sales": 80_721_186, "raw_materials": 29_774_131, "direct_labor": 10_782_720,
        "mfg_overhead": 7_159_162, "operating_expenses": 17_547_658},
}

rows = []
for year, items in annual_projections.items():
    for line_item, annual_value in items.items():
        rows.append({
            "cooperator": COOPERATOR,
            "year": year,
            "line_item": line_item,
            "annual_value": annual_value,
            "monthly_value": round(annual_value / 12, 2),
        })
financial_projections = pd.DataFrame(rows)
financial_projections.to_csv("financial_projections.csv", index=False)

# ---------------------------------------------------------------------------
# 3. MONTHLY ACTUALS  (SIMULATED — Year 1 only, months 1-9 reported)
#    Ratios below are hand-set to create a deliberate mix:
#      - Gross Sales: on track, minor positive noise
#      - Raw Materials: significant upward spike (review-worthy)
#      - Direct Labor: on track, minor noise
#      - Manufacturing Overhead: on track, minor noise
#      - Operating Expenses: trending up, crosses review threshold
#    Months 10-12 are intentionally left unreported to exercise the
#    "missing data" handling (monitoring status = In Progress).
# ---------------------------------------------------------------------------
MONITORED_YEAR = 1
REPORTED_MONTHS = 9

ratios = {
    "gross_sales":         [0.99, 1.02, 1.05, 1.01, 1.04, 1.06, 1.03, 1.05, 1.02],
    "raw_materials":       [1.05, 1.10, 1.18, 1.25, 1.30, 1.38, 1.35, 1.32, 1.30],
    "direct_labor":        [1.00, 1.03, 0.99, 1.02, 1.04, 1.03, 1.01, 1.03, 1.02],
    "mfg_overhead":        [1.02, 1.05, 1.03, 1.06, 1.04, 1.07, 1.05, 1.04, 1.06],
    "operating_expenses":  [1.08, 1.12, 1.15, 1.18, 1.20, 1.23, 1.19, 1.21, 1.20],
}

monthly_base = {
    li: annual_projections[MONITORED_YEAR][li] / 12
    for li in ratios
}

rows = []
for li, ratio_list in ratios.items():
    for m, ratio in enumerate(ratio_list, start=1):
        rows.append({
            "cooperator": COOPERATOR,
            "year": MONITORED_YEAR,
            "month": m,
            "line_item": li,
            "actual_value": round(monthly_base[li] * ratio, 2),
        })
monthly_actuals = pd.DataFrame(rows)
monthly_actuals.to_csv("monthly_actuals.csv", index=False)

# ---------------------------------------------------------------------------
# 4. REPAYMENT RECORDS  (SIMULATED — contractual due is fixed at the proposal's
#    monthly amortization; paid amounts are simulated with a mix of full,
#    insufficient, and over payments)
# ---------------------------------------------------------------------------
MONTHLY_AMORTIZATION = 81_360
paid_amounts = {
    1: 81_360, 2: 81_360, 3: 60_000, 4: 81_360, 5: 90_000,
    6: 81_360, 7: 50_000, 8: 81_360, 9: 81_360,
}
rows = []
for m in range(1, REPORTED_MONTHS + 1):
    rows.append({
        "cooperator": COOPERATOR,
        "year": MONITORED_YEAR,
        "month": m,
        "amount_due": MONTHLY_AMORTIZATION,
        "amount_paid": paid_amounts[m],
    })
repayment_records = pd.DataFrame(rows)
repayment_records.to_csv("repayment_records.csv", index=False)

# ---------------------------------------------------------------------------
# 5. APPRAISAL DATA  (from the proposal's Partial Budget Analysis / NPV / IRR
#    / ROI / BCR sections)
# ---------------------------------------------------------------------------
appraisal = pd.DataFrame([{
    "cooperator": COOPERATOR,
    "total_investment": 6_231_600,      # Year-0 net benefit inflow used as the ROI base
    "projected_roi": 1.7210,
    "projected_irr": 0.7334,
    "projected_npv_0pct": 50_122_852,
    "projected_bcr": 1.01,
}])
appraisal.to_csv("appraisal.csv", index=False)

# ---------------------------------------------------------------------------
# 6. APPROVED RISK / OBJECTIVE DATA  (from the proposal's Risk Management
#    table and Expected Output/Impact table)
# ---------------------------------------------------------------------------
risk_objectives = pd.DataFrame([
    {
        "cooperator": COOPERATOR,
        "objective": "Improve product quality (new product line, reduce monthly rejection and rework rate)",
        "risk": "Insufficient testing of the new product line could result in quality issues going unnoticed until commercialization. Assumes staff are well-trained and skilled in handling the new line and its production processes.",
        "mitigation": "Implement rigorous quality assurance processes throughout product development and production stages; conduct regular training to keep staff up to date with best practices and new processes.",
        "related_line_items": "raw_materials",
    },
    {
        "cooperator": COOPERATOR,
        "objective": "Increase process efficiency (reduce printing processing time)",
        "risk": "Staff might resist changes to the process or require additional training to adapt to new procedures. Assumes new processes/technologies integrate smoothly with existing workflows.",
        "mitigation": "Provide comprehensive training and support for staff; test new processes/technologies in a controlled environment before full implementation.",
        "related_line_items": "direct_labor;mfg_overhead",
    },
    {
        "cooperator": COOPERATOR,
        "objective": "Improve productivity through a smooth workflow",
        "risk": "Implementing changes may require additional resources (time, money, personnel) that are not available. Assumes employees will cooperate and engage positively with workflow changes.",
        "mitigation": "Create a resource plan and allocate budget for project implementation; engage employees throughout the process to ensure alignment and address concerns.",
        "related_line_items": "operating_expenses",
    },
    {
        "cooperator": COOPERATOR,
        "objective": "Generate at least one (1) additional production staff",
        "risk": "Hiring and onboarding a new staff member can be expensive and costly. Assumes suitable candidates meeting the qualifications and experience required will be available.",
        "mitigation": "Consider adjusting/reallocating resources to manage new-staff expenses; refine the hiring process with detailed job descriptions and clear requirements.",
        "related_line_items": "direct_labor",
    },
])
risk_objectives.to_csv("risk_objectives.csv", index=False)

# ---------------------------------------------------------------------------
# 7. SPECIFIC OBJECTIVE TARGETS (non-financial, from Table 14 Expected Output/Impact)
# ---------------------------------------------------------------------------
objective_targets = pd.DataFrame([
    {"cooperator": COOPERATOR, "metric": "Monthly rejection rate (sewing)", "baseline": 0.05, "target": 0.005},
    {"cooperator": COOPERATOR, "metric": "Rework rate", "baseline": 0.20, "target": 0.01},
    {"cooperator": COOPERATOR, "metric": "Rejection rate (eco-solvent printing)", "baseline": 0.15, "target": 0.02},
])
objective_targets.to_csv("objective_targets.csv", index=False)

print("Sample data files generated successfully in data/.")
