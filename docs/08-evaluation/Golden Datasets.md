# Golden Datasets

## Dataset Structure

Each golden dataset is a JSON file stored in `finance/evaluation/datasets/` organised by category. The schema follows the nested expectation model:

```json
{
  "metadata": {
    "id": "unique_identifier",
    "name": "Human Readable Name",
    "category": "financial_logic | data_quality | runtime_behaviour | governance",
    "subcategory": "specific_area",
    "description": "What this scenario tests",
    "tags": ["classification", "tags"],
    "difficulty": "basic | intermediate | advanced"
  },
  "input": {
    "query": "Natural language query for the harness",
    "context": {
      "accounts": [
        {"id": "4010", "name": "Revenue", "actual": 100000, "budget": 95000}
      ]
    }
  },
  "expected": {
    "planning": { ... },
    "execution": { ... },
    "verification": { ... },
    "reflection": { ... },
    "output": { ... }
  }
}
```

## Model Definition

```python
class GoldenDataset(BaseModel):
    metadata: DatasetMetadata
    input: DatasetInput
    expected: ExpectedBehaviour

class ExpectedBehaviour(BaseModel):
    planning: PlanningExpectation
    execution: ExecutionExpectation
    verification: VerificationExpectation
    reflection: ReflectionExpectation
    output: OutputExpectation
```

## How Datasets Map to Pipeline Stages

| Expectation | Pipeline Node | What's Measured |
|-------------|---------------|-----------------|
| `planning` | Planner | Intent coverage, action bounds, replan limits |
| `execution` | Executor | Success rate, retries, latency |
| `verification` | Verifier | Evidence quality, contradictions, confidence |
| `reflection` | Reflection | Decision correctness, gap detection |
| `output` | All | Variance accuracy, KPI accuracy, report coverage, claim bounds |

## Loading

The `GoldenDatasetLoader` discovers all JSON files recursively in the datasets directory. Built-in datasets (simple_001, seasonal_001) are constructed in code for backward compatibility.

```python
loader = GoldenDatasetLoader()
datasets = loader.load_all()  # 22+ datasets
ds = loader.load("revenue_growth")
```

## Python Factories

For programmatic use, `finance/evaluation/scenarios/factories.py` provides factory functions that load from JSON and apply overrides:

```python
from finance.evaluation.scenarios import revenue_growth

ds = revenue_growth(scale=2.0, currency="EUR")
ds = revenue_growth(overrides={"input.context.accounts.0.actual": 999999})
```
