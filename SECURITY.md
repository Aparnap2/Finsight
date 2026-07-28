# Security Policy for FinSight

## Secrets Management

### Environment Variables Only
- All secrets, API keys, and database credentials **must** be stored in environment variables, never in source code.
- Copy `.env.example` to `.env` for local development. The `.env` file is gitignored and must never be committed.
- Reference environment variables through `shared/config/config.py` — never access `os.environ` directly in application code.

### What Belongs in Environment Variables

| Secret | Example Variable | Location |
|--------|-----------------|----------|
| Database connection string | `POSTGRES_URI` | `.env` |
| LLM API key | `OPENAI_API_KEY` | `.env` |
| Langfuse credentials | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | `.env` |
| Redis connection | `REDIS_URL` | `.env` |
| Qdrant connection | `QDRANT_URL` | `.env` |

### Prohibited Practices
- No hardcoded secrets, tokens, or credentials in any file committed to the repository.
- No secrets in Dockerfiles, docker-compose files, or CI/CD configuration.
- No secrets in log output, error messages, or API responses.
- No committing `.env` files or any file containing real credentials.

---

## PII Handling

### Data Classification
FinSight may process financial records, employee data, and customer transaction data. Treat all data that can be linked to a natural person as **Personally Identifiable Information (PII)**.

### PII Rules
- **Minimization**: Only collect and process PII that is strictly necessary for FP&A operations.
- **Anonymization**: Aggregate or anonymize PII in reports, dashboards, and exported commentary.
- **Access**: PII must only be accessible to authenticated, authorized users. Role-based access control (RBAC) is enforced at the API layer.
- **Transmission**: All data in transit must use TLS 1.2 or higher. Internal service-to-service communication must also be encrypted.
- **Storage at rest**: PII stored in PostgreSQL and Qdrant must reside on encrypted volumes.

### Tenant Isolation
- FinSight uses a multi-tenant model keyed by `tenant_id` (e.g., `CF001`).
- All database queries filter by `tenant_id`. The API layer must validate that the authenticated user has access to the requested tenant.
- Vector embeddings in Qdrant must include `tenant_id` metadata to enforce isolation at query time.

---

## Financial Data Protection

### Sensitivity
Financial data (actuals, budgets, forecasts, variances) is classified as **highly sensitive**. Unauthorized disclosure could impact market position, stock price, or competitive standing.

### Protection Measures
- **Encryption at rest**: All financial data in PostgreSQL is stored on encrypted file systems.
- **Encryption in transit**: All API traffic must use HTTPS. Database connections must use TLS.
- **Access logging**: All queries to financial data must be logged with user identity, timestamp, and query scope.
- **Data masking**: API responses may apply data masking for non-privileged users (e.g., hiding specific account-level details).

### Monetary Value Handling
- All monetary values use `decimal.Decimal` with sufficient precision to prevent rounding errors that could lead to financial misstatement.
- Float types are explicitly rejected at the Pydantic serialization boundary in `apps/api/schemas.py`.

---

## Logging Practices

### What to Log
- Application-level events (pipeline start/complete, errors, degraded modes).
- Authentication and authorization decisions (login, logout, access denied).
- Data quality issues detected during validation.

### What NOT to Log
- API keys, tokens, or secrets of any kind.
- Full database connection strings containing credentials.
- Individual PII values (names, email addresses, employee IDs) — use anonymized references.
- Raw LLM prompts containing sensitive financial data (log prompt structure, not content).

### Log Levels
| Level | Usage |
|-------|-------|
| `ERROR` | Pipeline failures, unrecoverable errors, security violations |
| `WARNING` | Degraded modes, data quality issues, retry events |
| `INFO` | Pipeline lifecycle (started, completed), user actions |
| `DEBUG` | Development-only details, never enabled in production |

### Audit Trail
- All financial period transitions (open → closing → completed → locked) are recorded in an `audit_trail` field on the `FiscalPeriod` model.
- All assertion pipeline results and rejected claims are persisted for forensic review.

---

## Access Control Expectations

### API Layer
- All endpoints require authentication (token-based or session-based, depending on deployment).
- The API validates that the requesting user has permission for the specified `tenant_id`.
- Endpoints that expose financial data require elevated privileges.

### Agent Layer
- Agents do not directly authenticate users — they operate under the authority of the calling API context.
- LLM calls are made with service-level credentials, not end-user credentials.

### Infrastructure
- Database access is limited to the application service account. Direct database access for debugging requires temporary credentials.
- Redis and Qdrant are not exposed externally. They listen on internal Docker networks only.
- Temporal Server (workflow engine) requires mTLS or API token authentication in production.

---

## Data Retention Policies

### Retention Schedule

| Data Type | Retention Period | Rationale |
|-----------|-----------------|-----------|
| GL actuals and budgets | 7 years | Regulatory and audit requirements |
| Variance analyses | 7 years | Audit trail for financial reporting |
| Root cause findings | 3 years | Operational improvement reference |
| Commentary output | 3 years | Board meeting records |
| Pipeline run logs | 1 year | Debugging and performance analysis |
| LLM request/response logs | 90 days | Quality monitoring and hallucination analysis |
| Session tokens | Token lifetime | Security best practice |

### Data Deletion
- Hard deletion of financial records is prohibited — use soft deletion with a `deleted_at` timestamp.
- After the retention period, data is archived to cold storage before deletion.
- Tenant data deletion must be a complete, verified operation covering PostgreSQL, Qdrant, and Redis.

---

## Incident Response

### Security Incident Types
- **Data breach**: Unauthorized access to financial or PII data.
- **Credential compromise**: Leaked API keys or database credentials.
- **LLM data leakage**: Sensitive data appearing in LLM training or output.
- **Tenant boundary breach**: Unauthorized cross-tenant data access.

### Response Steps
1. **Identify**: Detect and confirm the incident via logging anomalies, alerts, or user report.
2. **Contain**: Revoke compromised credentials, isolate affected services, pause pipeline processing.
3. **Investigate**: Determine scope, affected data, and root cause.
4. **Remediate**: Fix the vulnerability, rotate secrets, notify affected parties.
5. **Document**: Record the incident in the security log and update policies as needed.

---

## Dependency Security

- All third-party dependencies are pinned to specific versions in `pyproject.toml`.
- Run `uv sync` with integrity verification where possible.
- Review dependency updates for known CVEs before merging.
- Prefer well-maintained, widely-audited libraries over niche alternatives.
