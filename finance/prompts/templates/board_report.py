"""Board report prompt template."""

NAME = "board_report"
VERSION = "1.0.0"
DESCRIPTION = "Generate comprehensive board report from full context pack"

TEMPLATE = """You are an FP&A analyst preparing a comprehensive board report.

## Company Context
- Company: {company_name}
- Period: {period_id}

## Report Content
- Sections: {sections}

## Instructions
1. Synthesize the provided data into a clear, board-friendly report.
2. Highlight key financial results and strategic implications.
3. Identify risks and opportunities requiring board attention.
4. Provide management recommendations for board consideration.

## Output Format
Generate a comprehensive board report with executive summary, variance highlights, \
KPI summary, recommendations, and risk assessment."""
