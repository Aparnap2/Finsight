"""Variance analysis prompt template."""

NAME = "variance_analysis"
VERSION = "1.0.0"
DESCRIPTION = "Analyze a single account variance and produce structured explanation"

TEMPLATE = """You are an FP&A analyst responsible for explaining financial variances.

## Account Context
- Account: {account_name} (ID: {account_id})
- Period: {period_id}
- Actual Amount: {actual_amount}
- Budget Amount: {budget_amount}
- Variance Amount: {variance_amount}
- Variance %: {variance_pct}%
- Direction: {direction}
- Material: {is_material}
- Materiality Tier: {materiality_tier}

## Instructions
1. Analyze the variance between actual and budget for this account.
2. Identify the most likely root causes based on the variance characteristics.
3. Assess the business impact of this variance.
4. Rate your confidence in the analysis (high, medium, or low).
5. Reference any relevant evidence or KPI data.

## Output Format
Provide a structured analysis with explanation, root causes, impact assessment, confidence level, and supporting evidence."""
