## ADDED Requirements

### Requirement: Layered Test Taxonomy With Simulators As Tools

The project SHALL classify every test under exactly one of fifteen categories: (1) unit, (2) financial-domain invariants, (3) database schema and integrity, (4) third-party contract, (5) mocked integration, (6) workflow and state machine, (7) policy and control, (8) security and privacy, (9) mocked end-to-end, (10) provider sandbox, (11) load and performance, (12) LLM evaluation, (13) migration and upgrade, (14) resilience and fault injection, (15) deployment and operational smoke.

A simulator (Mockoon, LocalStack, or any other stand-in for a third-party system) SHALL be recorded as the **tool** used by a test, never as a test category. A category describes what is verified; a tool describes how a dependency is stood in for.

A financial-domain invariant SHALL be owned by exactly one test file. Where a generic business-logic test and a financial-domain test cover the same rule, the two SHALL have separate ownership and separate assertions: the business-logic test verifies the rule, and the financial-domain test verifies that the rule still yields the correct ledger and settlement result under real financial edge cases (partial, duplicate, fee-bearing, reversed).

#### Scenario: A simulator is recorded as a tool

- **WHEN** a test exercises a provider adapter against a Mockoon or LocalStack simulation
- **THEN** the test's recorded category is the capability it verifies (for example "third-party contract" or "mocked integration"), and the simulator is recorded separately as the tool

#### Scenario: One financial invariant, one owning test file

- **WHEN** a financial invariant such as monetary conservation is enforced
- **THEN** the test inventory names exactly one owning test file for it, and any other file that also asserts it is recorded as a redundant enforcer rather than a second owner

### Requirement: Test Inventory Ratchet And Executability

The project SHALL maintain a machine-readable test inventory (`docs/testing/test-inventory.json`) mapping every test file to its category and to the CI gate that executes it. A CI gate SHALL fail the build when a test file is unlisted, when a category has no enforcing gate, or when a category marked merge-blocking has no job.

Every test file in the repository SHALL be executed by at least one workflow. A test that is collected but never executed SHALL be treated as a defect, not as coverage.

#### Scenario: An unlisted test file fails the build

- **WHEN** a new test file is added to `tests/` and is not present in the inventory
- **THEN** the inventory ratchet job fails and names the unlisted file

#### Scenario: A collected but unexecuted test is a defect

- **WHEN** a test file exists in `tests/` but no workflow path or marker selects it
- **THEN** the inventory records it as unexecuted and the release qualification treats it as an open gap

### Requirement: Risk-To-Test Matrix

The project SHALL maintain a matrix mapping every critical financial invariant, security boundary, and workflow transition to at least one enforcing test, naming the enforcing test file and the CI gate that executes it. An invariant with no enforcing test SHALL be recorded explicitly as `GAP`. A `GAP` in a merge-blocking category SHALL fail the inventory ratchet.

The matrix SHALL cover, at minimum, the money and arithmetic invariants, the reconciliation invariants, the financial-control invariants, and the ledger and audit invariants.

#### Scenario: An invariant with no enforcer is an explicit gap

- **WHEN** a critical financial invariant has no enforcing test
- **THEN** the matrix records it as `GAP` with the invariant ID, and the ratchet fails for the merge-blocking category it belongs to

#### Scenario: An LLM cannot grant itself authorization

- **WHEN** the matrix is checked for the control that separates proposal from authorization
- **THEN** it names a test file that proves a model-generated proposal cannot authorize its own execution, and names the gate that executes that file

### Requirement: Staged Gate Structure With Shared Gate Contract

CI SHALL be organized into five stages: (1) PR fast gate, (2) PR integration gate, (3) scheduled extended validation, (4) pre-release qualification, (5) post-deployment verification. Every job SHALL evaluate its result through one shared gate contract that owns log parsing, pass/fail/skip counting, the job's skip budget, named required-test assertions, and the emission of a machine-readable summary.

Stage 1 and Stage 2 SHALL run on every pull request. Stage 3 SHALL run on a schedule. Stage 4 SHALL run for a release candidate. Stage 5 SHALL run after deployment.

#### Scenario: The fast gate stays fast

- **WHEN** a pull request is opened
- **THEN** Stage 1 executes only fast deterministic checks and completes within its measured budget, and Stage 2 does not run inside the Stage 1 job

#### Scenario: One gate contract owns the verdict

- **WHEN** any job in any stage evaluates its result
- **THEN** it calls the shared gate contract rather than applying its own ad-hoc pass/fail parsing, and the contract emits a machine-readable summary artifact

### Requirement: Failure Semantics — A Skipped Test Is Not A Passing Test

A gate SHALL fail when: a required test fails; a required summary or artifact is missing; zero required tests executed; or a required evaluation was skipped. A gate SHALL report an explicit failed or inconclusive result when required infrastructure is unavailable. A gate SHALL NOT report success when required tests were skipped, when an evaluation did not run, or when the result of a check could not be determined.

Where a job declares a skip budget, the budget SHALL be a count AND the job SHALL assert the identity of the required tests it must execute.

#### Scenario: A required test is skipped

- **WHEN** a test named in the job's required-test list is skipped
- **THEN** the job fails, naming the skipped test, and does not report a green result

#### Scenario: Infrastructure failure is not a pass

- **WHEN** a required service is unreachable and the tests depending on it cannot run
- **THEN** the job fails or reports an explicit inconclusive result, and the run is never recorded as a passing gate

#### Scenario: Zero tests executed is a failure

- **WHEN** a test job completes having executed zero tests
- **THEN** the job fails, and the summary artifact records zero executed tests as the cause

### Requirement: Evidence And Reporting

Every CI job SHALL retain, with an explicit retention window: the raw teed test log, the machine-readable gate summary, coverage data where coverage is instrumented, evaluation results for LLM evaluation jobs, migration logs for migration jobs, and performance data for load jobs.

A release qualification SHALL be expressed as a list of run IDs and artifact references. A green status badge SHALL NOT by itself qualify a release.

#### Scenario: The fast gate retains its raw log

- **WHEN** the Stage 1 fast gate completes
- **THEN** the teed unit/contract log is uploaded as an artifact with a retention window, and is retrievable by run ID after the job finishes

#### Scenario: A release cites artifacts, not badges

- **WHEN** a release qualification is recorded
- **THEN** it lists the run IDs and artifact references that constitute the evidence, and the artifacts remain retrievable for the retention window

### Requirement: Release Policy Per Category

The project SHALL specify, for each test category, whether it blocks a merge, blocks a release, or is scheduled-only. Merge-blocking categories SHALL be limited to those whose failure implies incorrect financial state, unauthorized action, data exposure, invalid persisted state, or broken control flow. Load and performance, mutation testing, provider sandbox, and the full property-based suite SHALL be release-blocking rather than merge-blocking, because of their runtime cost.

A test failure caused by a real regression SHALL fail the gate. An infrastructure failure SHALL produce an explicit failed or inconclusive result and SHALL NOT be silently skipped.

#### Scenario: A load test does not block a merge

- **WHEN** a pull request is opened and a load test would fail
- **THEN** the merge is not blocked by that failure, and the release qualification for a release containing that change records the load result

#### Scenario: A financial invariant failure blocks the merge

- **WHEN** a test enforcing a critical financial invariant fails on a pull request
- **THEN** the merge is blocked and the failure is reported as a regression

### Requirement: Provider Contract And Sandbox Separation

Third-party integrations SHALL have two independent verification paths: a simulated contract suite that runs on every pull request, and a provider-sandbox suite that runs against the provider's own test environment before release. A simulated contract suite SHALL NOT be treated as evidence of compatibility with the real provider.

The provider-sandbox suite SHALL be built for the provider that the flagship workflow actually depends on. The project SHALL NOT introduce tests for a provider integration that is not part of the selected scope merely to make the test matrix appear comprehensive.

#### Scenario: A simulation is not sandbox evidence

- **WHEN** a provider contract suite passes entirely against a simulator
- **THEN** the release qualification does not record provider compatibility as verified, and the sandbox suite remains required

#### Scenario: No out-of-scope provider tests

- **WHEN** the accounting provider for the flagship path is a fixture rather than a named external integration
- **THEN** no tests are introduced for a different external accounting provider solely to broaden the matrix

### Requirement: Structured LLM Evaluation Without Output Equality

LLM evaluation SHALL assess structured-output validity, evidence grounding, policy compliance, calibrated confidence, and the rejection of invalid proposals. LLM evaluation SHALL NOT assert exact output equality, and no financial invariant SHALL be delegated to a model. The critical financial safety checks SHALL remain deterministic.

#### Scenario: An unsupported hypothesis is rejected

- **WHEN** the LLM proposes a hypothesis that the evidence does not support
- **THEN** the evaluation records the proposal as rejected on grounding grounds, and the check is expressed as a threshold over structured metrics rather than a string comparison

#### Scenario: Financial safety stays deterministic

- **WHEN** any financial invariant is evaluated
- **THEN** the enforcing test is a deterministic test, and no model output participates in the verdict
