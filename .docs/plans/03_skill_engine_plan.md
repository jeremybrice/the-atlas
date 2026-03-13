# Domain 3: Skill Engine — Architectural Design Plan

## 1. Architecture Overview

The Skill Engine is what makes ATLAS capable and self-improving. It manages the complete lifecycle of skills: registration, discovery, invocation, composition, and critically, autonomous creation of new skills when capability gaps are identified.

The architecture has three layers: a **Skill Registry** that catalogs all available capabilities, an **Execution Runtime** that handles invocation and workflow orchestration, and a **Skill Forge** that creates new skills autonomously. The existing Forge plugins serve as seed skills that are migrated into the registry at startup.

```
                    ┌──────────────────────────────┐
                    │         Skill Forge           │
                    │  (gap detection, authoring,   │
                    │   testing, registration)      │
                    └──────────────┬───────────────┘
                                   │ creates
                    ┌──────────────▼───────────────┐
                    │        Skill Registry         │
                    │  (catalog, search, metadata,  │
                    │   versioning, dependencies)   │
                    └──────────────┬───────────────┘
                                   │ provides
          ┌────────────────────────┼────────────────────────┐
          │                        │                         │
   ┌──────▼──────┐    ┌───────────▼──────────┐    ┌────────▼────────┐
   │  Invocation │    │  Workflow Composer    │    │  Skill Evolver  │
   │  Runtime    │    │  (chaining, parallel, │    │  (metrics,      │
   │  (execute,  │    │   conditional, error  │    │   improvement,  │
   │   validate, │    │   recovery)           │    │   deprecation)  │
   │   sandbox)  │    └──────────────────────┘    └─────────────────┘
   └─────────────┘
```

## 2. Component Breakdown

### 2.1 Skill Registry
**Responsibility**: Central catalog of all available skills with search and discovery capabilities.

Maintains a structured index of every registered skill: its descriptor (name, description, input/output schemas, preconditions, resource requirements), its implementation reference (Python module, CLI command template, Claude Code prompt), its maturity level, and its execution history summary.

**Public Interface**:
- `register(skill: SkillDefinition) -> SkillId`
- `unregister(skill_id: SkillId) -> None`
- `get(skill_id: SkillId) -> SkillDefinition`
- `search(query: CapabilityQuery) -> list[SkillDescriptor]`
- `list_all(filter: SkillFilter) -> list[SkillDescriptor]`
- `update_metadata(skill_id: SkillId, metadata: dict) -> None`

**Internal Structure**: SQLite-backed catalog with full-text search on skill descriptions. In-memory index for fast capability matching. Watches the skills directory for hot-reloading new skills.

### 2.2 Invocation Runtime
**Responsibility**: Execute a single skill with full lifecycle management.

Handles: input validation against the skill's input schema, Control Plane permission check, environment resource acquisition (via Environment Interface), execution in the appropriate mode (Python function call, subprocess, Claude Code prompt), output capture and validation against the output schema, timeout enforcement, error capture, and result packaging.

**Public Interface**:
- `invoke(skill_id: SkillId, params: dict, context: InvocationContext) -> SkillResult`
- `invoke_async(skill_id: SkillId, params: dict, context: InvocationContext) -> Future[SkillResult]`
- `cancel(invocation_id: InvocationId) -> None`

**Dependencies**: Environment Interface (for subprocess execution, file I/O), Control Plane (permission checks), Memory System (execution history recording).

### 2.3 Workflow Composer
**Responsibility**: Composes multiple skills into executable workflows.

The Agent Core's task graphs reference skills; the Workflow Composer handles the actual orchestration of multi-skill execution. Supports: sequential composition (output of A feeds input of B), parallel execution (A and B run concurrently), conditional branching (if A returns X, run B; else run C), error recovery (if A fails, try alternative D), data transformation (adapt A's output format to B's input format), and loop constructs (repeat A until condition met).

**Public Interface**:
- `compose(workflow_def: WorkflowDefinition) -> ComposedWorkflow`
- `execute(workflow: ComposedWorkflow, initial_params: dict) -> WorkflowResult`
- `validate(workflow_def: WorkflowDefinition) -> ValidationResult`

### 2.4 Skill Forge
**Responsibility**: Autonomously creates new skills when the agent identifies a capability gap.

This is the self-improvement engine. The creation flow:
1. Agent Core reports a capability gap ("I need a skill that can X but none exists")
2. Skill Forge analyzes the requirement
3. Queries Memory System for similar past attempts and relevant knowledge
4. Generates a skill specification (description, schemas, implementation plan) via Claude Code
5. Generates implementation code via Claude Code
6. Generates test cases via Claude Code
7. Executes tests in a sandboxed environment (via Environment Interface)
8. If tests pass, registers the skill in the Registry
9. Records the entire authoring episode in Memory System

The Forge leverages the existing skill-creator framework patterns as its foundation.

**Public Interface**:
- `create_skill(requirement: SkillRequirement) -> SkillCreationResult`
- `improve_skill(skill_id: SkillId, feedback: SkillFeedback) -> SkillCreationResult`
- `get_creation_status(creation_id: CreationId) -> CreationStatus`

**Dependencies**: Memory System (past attempts, domain knowledge), Environment Interface (sandbox for testing), Control Plane (approval for registration), Claude Code bridge (all generation steps).

### 2.5 Skill Evolver
**Responsibility**: Tracks skill performance and triggers improvement when warranted.

After each invocation, the Evolver records metrics: success/failure, execution time, resource usage, user satisfaction (if available). Periodically reviews metrics to: identify degrading skills (increasing failure rate), identify improvement opportunities (common parameter patterns that could be defaults), suggest skill deprecation (superseded by better alternatives), and trigger the Skill Forge for improvement iterations.

**Public Interface**:
- `record_execution(skill_id: SkillId, metrics: ExecutionMetrics) -> None`
- `get_skill_health(skill_id: SkillId) -> SkillHealthReport`
- `get_improvement_candidates() -> list[ImprovementCandidate]`
- `trigger_improvement(skill_id: SkillId, reason: str) -> CreationId`

## 3. Data Models

### SkillDefinition
The complete definition of a skill.
- `skill_id`: string (unique, human-readable, e.g., "file.search_and_replace")
- `version`: semver string
- `name`: string
- `description`: string (natural language, used for capability matching)
- `author`: enum (human, atlas_forge, migrated_forge_plugin)
- `skill_type`: enum (python_function, cli_command, claude_code_prompt, workflow)
- `input_schema`: JSON Schema
- `output_schema`: JSON Schema
- `preconditions`: list[Precondition] (e.g., "file must exist", "network available")
- `postconditions`: list[Postcondition]
- `resource_requirements`: list[ResourceRequirement] (e.g., "filesystem_write", "network_http")
- `risk_level`: enum (low, medium, high, critical)
- `implementation_ref`: string (module path, command template, or prompt template path)
- `test_ref`: string (path to test module)
- `maturity`: enum (draft, testing, stable, deprecated)
- `tags`: list[string]
- `created_at`, `updated_at`: datetime
- Storage: SQLite (metadata) + filesystem (implementation files in skills directory).

### SkillDescriptor
Lightweight view of a skill for search results and capability matching.
- `skill_id`, `name`, `description`, `input_schema`, `output_schema`, `maturity`, `tags`, `risk_level`
- Storage: In-memory cache, derived from SkillDefinition.

### SkillResult
- `invocation_id`: UUID
- `skill_id`: string
- `status`: enum (success, failure, timeout, cancelled)
- `output`: JSON (conforms to output_schema)
- `error`: string | None
- `execution_time_ms`: int
- `resource_usage`: dict
- Storage: In-memory (passed to caller), summary written to episodic memory.

### WorkflowDefinition
- `workflow_id`: string
- `name`: string
- `steps`: list[WorkflowStep]
- `error_handlers`: dict[str, WorkflowStep] (fallback steps keyed by error type)
- Storage: JSON files in workflows directory.

### WorkflowStep
- `step_id`: string
- `step_type`: enum (skill_invoke, transform, condition, parallel_group, loop)
- `skill_id`: string | None (for skill_invoke type)
- `params_mapping`: dict (maps workflow variables to skill params)
- `output_mapping`: dict (maps skill output to workflow variables)
- `condition`: string | None (for condition type)
- `on_failure`: enum (abort, skip, retry, fallback)

### SkillRequirement
Input to the Skill Forge for autonomous creation.
- `description`: string (natural language description of needed capability)
- `example_inputs`: list[dict]
- `expected_outputs`: list[dict]
- `context`: string (why this skill is needed, what task triggered the gap)
- `suggested_approach`: string | None (optional hint from Agent Core)
- `priority`: enum (low, normal, high)

## 4. Interface Contracts

### Skill Engine → Agent Core
```python
# Capability queries (synchronous)
skills.search(query: CapabilityQuery) -> list[SkillDescriptor]
skills.get(skill_id: str) -> SkillDefinition

# Execution (async)
skills.invoke(skill_id: str, params: dict, context: InvocationContext) -> SkillResult

# Gap filling (async, may take minutes)
skills.create_skill(requirement: SkillRequirement) -> SkillCreationResult
```

### Skill Engine → Memory System
```python
# Procedural memory (bidirectional)
memory.get_procedures(task_type: str) -> list[Procedure]
memory.store_procedure(proc: Procedure) -> ProcedureId
memory.record_skill_execution(skill_id: str, outcome: ExecutionOutcome) -> None

# Episodic memory for skill authoring
memory.get_skill_history(skill_id: str) -> list[Episode]
memory.search_episodes(query: str) -> list[Episode]
```

### Skill Engine → Environment Interface
```python
# Skill execution environment
env.execute_command(cmd: str, cwd: str, timeout: int) -> CommandResult
env.read_file(path: str) -> str
env.write_file(path: str, content: str) -> None

# Sandboxed testing during skill creation
env.create_sandbox(config: SandboxConfig) -> SandboxId
env.execute_in_sandbox(sandbox_id: SandboxId, cmd: str) -> CommandResult
env.destroy_sandbox(sandbox_id: SandboxId) -> None
```

### Skill Engine → Control Plane
```python
# Permission checks
control.check_skill_invoke(skill_id: str, risk_level: str) -> PermissionResult
control.check_skill_creation(requirement: SkillRequirement) -> PermissionResult

# Audit
control.log_skill_invocation(entry: SkillAuditEntry) -> None
control.log_skill_creation(entry: CreationAuditEntry) -> None
```

## 5. State Management

**Skill Lifecycle**: `draft → testing → stable → deprecated`. New skills (including self-authored ones) start as `draft`. After passing tests, they move to `testing` (used with extra monitoring). After successful real-world invocations, they graduate to `stable`. Skills can be `deprecated` when superseded. Deprecated skills remain invocable but are excluded from capability search results.

**Invocation Lifecycle**: `validating → approved → executing → completed | failed | timeout | cancelled`. The `approved` state represents the Control Plane gate.

**Skill Creation Lifecycle**: `analyzing → designing → implementing → testing → registering → completed | failed`. Each state is checkpointed so creation can resume after interruption.

**Recovery**: The Registry persists to SQLite and rebuilds its in-memory index on startup. In-progress skill creations are checkpointed to disk and can be resumed. In-flight invocations are lost on restart (the Agent Core will re-dispatch them).

## 6. Design Patterns

- **Registry Pattern**: Central skill catalog with search and CRUD operations.
- **Factory Pattern**: Skill Forge creates skill instances through a standardized creation pipeline.
- **Strategy Pattern**: Different execution strategies for different skill types (Python, CLI, Claude Code, workflow).
- **Chain of Responsibility**: Invocation pipeline (validate → approve → execute → capture → record) where each handler can short-circuit.
- **Template Method**: Skill creation follows a fixed pipeline but each step (analyze, design, implement, test) has pluggable implementations.
- **Composite Pattern**: Workflows compose individual skills into tree structures.

## 7. Phased Rollout

**Phase 1 (MVP)**: Skill Registry with manual registration. Invocation Runtime supporting Python functions and CLI commands. Basic capability search (keyword matching). Forge plugin migration for 2 to 3 existing plugins (slack-inbox-scanner, jira-activity-scanner, product-forge-local). No Skill Forge (no autonomous creation). No Workflow Composer (single-skill invocations only). No Skill Evolver.

**Phase 2 (Full)**: Skill Forge with Claude Code-powered autonomous creation and testing. Workflow Composer with sequential and conditional composition. Skill Evolver with metrics tracking and improvement triggers. Full Forge plugin migration (all 7 plugins). Claude Code prompt-type skills (LLM-powered skills). Skill dependency management.

**Phase 3 (Advanced)**: Parallel workflow execution. Self-improving skill chains (workflows that optimize themselves based on execution history). Skill marketplace (export/import skills between ATLAS instances). Natural language skill invocation ("just do X" without specifying which skill). Skill composition suggestions (Agent Core gets recommended workflows for novel tasks).

## 8. Key Tradeoffs

**Skill definition richness vs. authoring friction**: Chose rich definitions (schemas, preconditions, risk levels). This adds overhead when creating skills manually but enables autonomous capability matching and safe self-authoring. The Skill Forge generates all this metadata automatically, so the friction is only for human-authored skills.

**File-based skill storage vs. database-only**: Chose hybrid. Skill metadata lives in SQLite for fast queries. Implementation files live on the filesystem for easy human inspection and version control. This mirrors how developers actually work with code.

**Strict schema validation vs. flexible typing**: Chose strict for registered skills, flexible for draft skills. Self-authored skills start with loose schemas that tighten as they mature. This balances safety with the agent's ability to experiment.

**Sandboxed testing vs. live testing**: Chose sandboxed for new/modified skills. Testing in the live environment risks side effects. The sandbox (via Environment Interface) provides isolation at the cost of some setup overhead.

## 9. Open Questions

- How should capability search work beyond keyword matching? Embedding-based semantic search would be more powerful but adds complexity. Should this mirror the Memory System's search evolution?
- What is the right granularity for skill decomposition? A "send Slack message" skill is too granular; a "manage entire project" skill is too coarse. Where's the sweet spot?
- How should skills handle secrets and credentials? Should skills declare their credential requirements, or should the Integration Layer inject credentials transparently?
- How does skill versioning interact with workflow composition? If a workflow references skill v1.0 and it's updated to v1.1, does the workflow auto-update or pin to the old version?
- What is the maximum complexity of self-authored skills? Should the Forge attempt complex multi-file Python packages, or stick to single-file scripts?
