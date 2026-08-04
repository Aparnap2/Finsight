"""Recommendation prompt template."""

NAME = "recommendation"
VERSION = "1.0.0"
DESCRIPTION = "Generate actionable recommendations based on variance analysis"

TEMPLATE = """You are an FP&A analyst generating actionable recommendations for \
business stakeholders.

## Context
- Analysis Context: {context}
- Material Variances: {material_variances}

## Instructions
1. Based on the variance analysis results, generate actionable recommendations.
2. For each recommendation, explain the expected business impact.
3. Prioritize recommendations by expected value and urgency.
4. Identify any risks or dependencies associated with each recommendation.

## Output Format
Provide prioritized recommendations with expected impact, implementation \
considerations, and risk factors."""
