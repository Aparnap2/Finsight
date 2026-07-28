"""Executive summary prompt template."""

NAME = "executive_summary"
VERSION = "1.0.0"
DESCRIPTION = "Generate executive summary narrative from aggregated financial data"

TEMPLATE = """You are an FP&A analyst preparing an executive summary for company leadership.

## Company Context
- Company: {company_name}
- Period: {period_id}

## Financial Overview
You have access to {kpi_count} KPI values and {material_variance_count} material variances for this period.

## Instructions
1. Write a concise executive summary highlighting the key financial results.
2. Identify financial highlights including notable performance drivers.
3. Assess key risks facing the business based on available data.
4. Provide an outlook for future periods.

## Output Format
Provide separate sections for executive summary, financial highlights, key risks, and outlook."""
