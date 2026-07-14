def search_historical_variances(query: str) -> list[dict]:
    return [{"query": query, "match": "Similar variance found in Q2 2025"}]


def search_finance_policy(query: str) -> list[dict]:
    return [{"query": query, "policy": "Revenue recognition policy ASC 606"}]
