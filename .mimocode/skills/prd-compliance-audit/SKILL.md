---
name: prd-compliance-audit
description: Audit a codebase against its PRD to produce a structured gap analysis — what's implemented, what's partial, what's missing, and an overall completion percentage. Supports standard and FDE evaluation modes.
---

# PRD Compliance Audit

Systematically compare a project's PRD against its actual codebase implementation. Produces a structured gap analysis report with per-section status, completion percentage, and actionable next steps.

## When to use

- User asks: "is this project complete per the PRD?"
- User asks: "what's left to implement?"
- User asks: "how far is this project from completion?"
- User asks: "tell me what this project does and how far it is from completion"
- New session start on an existing project where a PRD exists

## Inputs required

1. **PRD file path** — usually `prd.md`, `PRD.md`, `FinSight_PRD.md`, `Product_Requirements.md`, or similar in the project root
2. **Codebase root directory** — the project being audited
3. **Mode** (optional) — `standard` (default) or `fde` (Forward Deployed Engineer evaluation lens)

## Procedure

### Step 1: Locate and read the PRD

```
Find the PRD file in the project root. Common names:
  prd.md, PRD.md, *_PRD.md, Product_Requirements.md, requirements.md

Read the full PRD. Extract:
  - Project identity and goals
  - Tech stack requirements
  - Feature list / ship order
  - Architecture specifications
  - Test requirements
  - Any acceptance criteria or checklists
```

### Step 2: Explore the codebase structure

```
Map the directory tree. Identify:
  - Languages and frameworks in use
  - Directory structure (src/, tests/, config/, etc.)
  - Key entry points (main.go, app.py, server.ts, etc.)
  - Database schemas / migrations
  - Docker / CI configuration
  - Test directories and what they cover
```

### Step 3: Map PRD sections to implementation

For **each major PRD section**, check:

| PRD Section | Implementation Status | Evidence |
|---|---|---|
| [section name] | ✅ Done / 🟡 Partial / ❌ Missing | [file path + line reference] |

**Rules for status assignment:**
- ✅ **Done**: Feature is implemented, has tests, and matches PRD spec
- 🟡 **Partial**: Core logic exists but missing edge cases, tests, integrations, or deviates from PRD spec
- ❌ **Missing**: No implementation found, or only scaffold/placeholder code

### Step 4: Identify architecture drift

Compare PRD-specified architecture against actual implementation:
- Are the right technologies being used?
- Are there deviations from the PRD's data model?
- Are third-party integrations wired correctly?
- Is the authentication/authorization as specified?

### Step 5: Quantify completion

```
Calculate:
  - Total PRD sections: N
  - Completed (✅): X
  - Partial (🟡): Y
  - Missing (❌): Z
  - Overall completion: (X + Y*0.5) / N * 100%
```

### Step 6: Produce the report

Format the output as:

```markdown
## PRD Compliance Audit: [Project Name]

**Overall: ~[X]% Complete**

### ✅ Completed
| PRD Item | Status |
|----------|--------|
| [item] | ✅ Done — [brief evidence] |

### 🟡 Partial
| PRD Item | Status | Gap |
|----------|--------|-----|
| [item] | 🟡 Partial | [what's missing] |

### ❌ Missing
| PRD Item | Status |
|----------|--------|
| [item] | ❌ Missing — [what needs to be built] |

### Architecture Drift
- [deviation 1]: PRD says X, implementation uses Y
- [deviation 2]: ...

### Key Findings
- [important discovery 1]
- [important discovery 2]

### Recommended Next Steps
1. [highest priority missing item]
2. [next priority]
3. ...
```

## FDE Mode variant

When mode is `fde`, augment the standard audit with the FDE evaluation framework:

1. **Business Workflow (30%)**: Map the end-to-end SOP encoded in code. What business process does this automate? What are the steps?
2. **Integrations (30%)**: Map all external system integrations — APIs, databases, third-party services. For each: auth mechanism, retry logic, error handling, graceful degradation.
3. **Data Cleanup (20%)**: Trace data flow from input to output. What transformations happen? What validation/cleanup is performed?
4. **AI/ML Components (20%)**: Where is AI inserted into workflows? What does it decide vs what is deterministic? What is the bounded autonomy level?

FDE-specific rules:
- Never start with "Can AI call this API?" — start with "Should AI call this API?"
- Map Integration Maturity Levels: Level 1 (Read Only) → Level 2 (Assist) → Level 3 (Execute) → Level 4 (Autonomous)
- Production pattern: System → Adapter Layer → Workflow Layer → Agent Layer
- "Most integration bugs are data-flow bugs" — always map data flow first

## Output file

Save the report to `[project_root]/PRD_AUDIT_REPORT.md` unless the user requests a different location.

## Example sessions

This skill was derived from these repeated workflows:
- **OpsCore** (Jun 16): "tell me what this project does and how far it is from completion" → full codebase exploration + gap analysis → ~60-65% complete
- **SupportOps AI** (Jun 21): "tell me if the project is completed as per prd or not" → PRD compliance audit → ~70% complete, then implemented missing pieces
- **3PL Exception Handling** (Jun 19): FDE evaluation of existing codebase → comprehensive audit report across 4 FDE dimensions
