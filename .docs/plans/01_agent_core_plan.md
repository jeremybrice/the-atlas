# Domain 1: Agent Core — Architectural Design Plan

## 1. Architecture Overview

The Agent Core is the central nervous system of ATLAS. It owns the reasoning loop: receiving inputs (user goals, system triggers, skill results, environment observations), deciding what to do, coordinating execution across other domains, and reflecting on outcomes. It does not perform actions itself; it orchestrates.

The core is built around an **event-driven task processing pipeline**. Everything that happens in ATLAS — a user issuing a goal, a file change trigger firing, a skill completing — is an event. Events flow into the pipeline, get classified, prioritized, and either spawn new tasks or advance existing ones.

```
                        ┌─────────────────────┐
                        │   Event Ingress      │
                        │  (goals, triggers,   │
                        │   results, signals)  │
                        └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
                        │   Event Classifier   │
                        │  & Priority Router   │
                        └─────────┬───────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                │                 │                  │
       ┌────────▼──────┐  ┌──────▼───────┐  ┌──────▼───────┐
       │  Task Queue    │  │  Mission     │  │  Reactive    │
       │  Manager       │  │  Planner     │  │  Evaluator   │
       └────────┬──────┘  └──────┬───────┘  └──────┬───────┘
                │                │                  │
                └─────────────────┼─────────────────┘
                                  │
                        ┌─────────▼───────────┐
                        │   Execution Loop     │
                        │  (plan → act →       │
                        │   observe → reflect) │
                        └─────────┬───────────┘
                                  │
                    ┌─────────────┼──────────────┐
                    │             │               │
           ┌────────▼──┐  ┌──────▼─────┐  ┌─────▼──────┐
           │  Skill     │  │ Environment│  │  Control   │
           │  Engine    │  │ Interface  │  │  Plane     │
           │  (D3)      │  │ (D4)       │  │  (D6)      │
           └───────────┘  └────────────┘  └────────────┘
```

## 2. Component Breakdown

### 2.1 Event Ingress
**Responsibility**: Single entry point for all events entering the Agent Core.

Receives events from: the user (goals, commands), the Observation Engine in Environment Interface (triggers), skill completions, timer expirations, and Control Plane signals (pause/resume). Normalizes all inputs into a standard `AtlasEvent` format before passing downstream.

**Public Interface**:
- `submit_event(event: AtlasEvent) -> EventAck`
- `submit_goal(goal: UserGoal) -> MissionId`
- `submit_trigger(trigger: ObservationEvent) -> EventAck`

**Dependencies**: Control Plane (event logging), Memory System (event persistence).

### 2.2 Event Classifier & Priority Router
**Responsibility**: Determines what kind of event arrived and routes it to the correct handler.

Classifications: `new_mission` (user goal → Mission Planner), `trigger_event` (observation → Reactive Evaluator), `task_result` (skill/action completed → Task Queue Manager), `control_signal` (pause/resume/kill → direct handler), `system_event` (health/error → logging).

Priority is computed based on: event source (user > trigger > system), urgency metadata, current task queue depth, and Control Plane autonomy rules.

**Public Interface**:
- `classify(event: AtlasEvent) -> ClassifiedEvent`
- `compute_priority(event: ClassifiedEvent) -> PriorityScore`

### 2.3 Mission Planner
**Responsibility**: Decomposes high-level user goals into executable task graphs.

This is the most LLM-intensive component. When a user submits a goal, the Mission Planner: queries Memory System for relevant context, queries Skill Engine for available capabilities, constructs a prompt for Claude Code CLI that includes goal, context, and capabilities, parses Claude's response into a structured task graph, validates the graph (all referenced skills exist, dependencies are acyclic), and submits the graph to the Task Queue Manager.

Planning is iterative. The initial plan may be rough; as tasks execute and the agent learns more, the planner refines the remaining plan. This is the "replan on new information" pattern.

**Public Interface**:
- `plan_mission(goal: UserGoal, context: PlanningContext) -> TaskGraph`
- `replan(mission_id: MissionId, new_info: Observation) -> TaskGraph`

**Dependencies**: Memory System (context retrieval), Skill Engine (capability catalog), Claude Code bridge.

### 2.4 Reactive Evaluator
**Responsibility**: Decides whether observation events require action and what action to take.

When a trigger fires (file changed, Slack message, scheduled time), the Reactive Evaluator: checks the trigger against registered reaction rules, evaluates whether the trigger context warrants action (using a lightweight Claude Code call if needed), and either spawns a task directly or escalates to the Mission Planner for complex reactions.

Reaction rules are stored in configuration and can be learned over time (if the user always wants a certain response to a certain trigger, the agent learns the pattern).

**Public Interface**:
- `evaluate(trigger: ObservationEvent) -> ReactionDecision`
- `register_rule(rule: ReactionRule) -> RuleId`

### 2.5 Task Queue Manager
**Responsibility**: Owns the ordered queue of all pending and active tasks.

Manages: task priority ordering, dependency resolution (task B waits until task A completes), concurrency limits (max N tasks executing simultaneously), task state lifecycle (pending → ready → executing → completed/failed), and preemption (high-priority task can pause a lower-priority one).

Tasks are persisted to SQLite so the queue survives daemon restarts. On restart, the manager loads pending/executing tasks and resumes or retries them.

**Public Interface**:
- `enqueue(task: Task, priority: PriorityScore) -> TaskId`
- `enqueue_graph(graph: TaskGraph) -> list[TaskId]`
- `get_next_ready() -> Task | None`
- `complete(task_id: TaskId, result: TaskResult)`
- `fail(task_id: TaskId, error: TaskError)`
- `get_queue_state() -> QueueSnapshot`

### 2.6 Execution Loop
**Responsibility**: The central plan-act-observe-reflect cycle that drives task execution.

The loop runs continuously while tasks are in the queue. Each iteration: pulls the next ready task, checks Control Plane for approval if required, dispatches to the appropriate executor (Skill Engine for skill tasks, Environment Interface for direct actions), waits for the result, writes the outcome to Memory System, reflects on the result (did it achieve the expected outcome?), and advances or adjusts the task graph.

Reflection is a lightweight Claude Code call that compares expected vs. actual outcomes and decides: continue plan as-is, replan, escalate to user, or mark mission complete.

**Public Interface**:
- `start() -> None` (begins the loop)
- `pause() -> None`
- `resume() -> None`
- `step() -> ExecutionStepResult` (execute one step, used for debugging)

## 3. Data Models

### AtlasEvent
Core event type flowing through the system.
- `event_id`: UUID
- `event_type`: enum (goal, trigger, task_result, control_signal, system)
- `source`: string (user, observation_engine, skill_engine, control_plane)
- `payload`: JSON (type-specific data)
- `timestamp`: datetime
- `priority_hint`: int (optional, source-provided)
- Storage: In-memory during processing; written to episodic memory on completion.

### Mission
A user-assigned goal with its associated plan and state.
- `mission_id`: UUID
- `goal_text`: string (the user's original goal statement)
- `status`: enum (planning, active, paused, completed, failed, cancelled)
- `task_graph`: TaskGraph (the decomposed plan)
- `context_snapshot`: JSON (memory context at planning time)
- `created_at`, `updated_at`: datetime
- `priority`: int
- Storage: SQLite (survives restarts).

### Task
A single executable unit of work within a mission or standalone.
- `task_id`: UUID
- `mission_id`: UUID | None (null for standalone reactive tasks)
- `description`: string
- `task_type`: enum (skill_invocation, environment_action, planning_step, approval_gate)
- `skill_id`: string | None
- `input_params`: JSON
- `expected_outcome`: string
- `status`: enum (pending, ready, executing, waiting_approval, completed, failed, cancelled)
- `result`: JSON | None
- `depends_on`: list[TaskId]
- `priority`: int
- `retry_count`: int
- `max_retries`: int
- Storage: SQLite.

### TaskGraph
A directed acyclic graph of tasks representing a mission's execution plan.
- `graph_id`: UUID
- `mission_id`: UUID
- `nodes`: dict[TaskId, Task]
- `edges`: list[tuple[TaskId, TaskId]] (dependency edges)
- `version`: int (incremented on replan)
- Storage: SQLite (serialized as JSON).

## 4. Interface Contracts

### Agent Core → Memory System
```python
# Synchronous reads for planning context
memory.retrieve_context(query: str, max_tokens: int) -> ContextBundle
memory.get_recent_episodes(n: int, filter: EpisodeFilter) -> list[Episode]

# Async writes for recording outcomes
memory.record_episode(episode: Episode) -> EpisodeId
memory.update_working_memory(key: str, value: Any) -> None
```

### Agent Core → Skill Engine
```python
# Synchronous capability queries
skills.find_skills(capability_query: str) -> list[SkillDescriptor]
skills.get_skill(skill_id: str) -> SkillDescriptor

# Async skill execution
skills.invoke(skill_id: str, params: dict) -> SkillResult
skills.request_skill_creation(requirement: SkillRequirement) -> SkillCreationResult
```

### Agent Core → Environment Interface
```python
# Async action execution
env.execute_action(action: EnvironmentAction) -> ActionResult
env.get_state() -> EnvironmentState

# Observation subscription
env.subscribe(filter: ObservationFilter, callback: Callable) -> SubscriptionId
```

### Agent Core → Control Plane
```python
# Synchronous approval checks (must be fast)
control.check_permission(action: ProposedAction) -> PermissionResult
control.get_autonomy_level(domain: str, skill: str) -> AutonomyLevel

# Async event reporting
control.log_action(entry: AuditEntry) -> None
control.request_approval(request: ApprovalRequest) -> ApprovalResult
```

## 5. State Management

**Mission Lifecycle**: `planning → active → completed | failed | cancelled`. Can transition to `paused` from any active state and back.

**Task Lifecycle**: `pending → ready → executing → completed | failed`. Tasks move from `pending` to `ready` when all dependencies are satisfied. Can enter `waiting_approval` from `ready` if Control Plane requires it.

**Recovery on Restart**: The daemon loads all non-terminal missions and tasks from SQLite. Tasks in `executing` state are transitioned to `ready` for re-execution (they may have been interrupted). The Execution Loop resumes from the current queue state.

## 6. Design Patterns

- **Event-Driven Architecture**: All inputs are events, enabling loose coupling and easy extensibility.
- **Command Pattern**: Each task is a serializable command object that can be queued, persisted, and retried.
- **Strategy Pattern**: The Execution Loop uses strategy objects for different task types (skill invocation vs. environment action vs. planning step).
- **Observer Pattern**: The Core subscribes to observation events from Environment Interface.
- **Circuit Breaker**: If Claude Code CLI calls fail repeatedly, the core backs off rather than flooding requests.

## 7. Phased Rollout

**Phase 1 (MVP)**: Single-threaded execution loop. User submits goals via CLI. Simple linear task decomposition (no parallel tasks). Basic priority queue (FIFO with manual priority). Memory reads/writes for context. Control Plane approval checks. No reactive mode yet.

**Phase 2 (Full)**: Reactive mode with observation subscriptions. Full task graph support with parallel execution. Iterative replanning on new information. Preemptive priority scheduling. Persistent mission recovery across restarts.

**Phase 3 (Advanced)**: Multi-agent support (multiple execution loops for parallel missions). Predictive planning (pre-decompose likely next goals). Cross-mission learning (similar goals reuse prior plans). Natural language mission monitoring ("what are you working on?").

## 8. Key Tradeoffs

**Event-driven vs. direct function calls**: Chose event-driven for extensibility and loose coupling. Direct calls would be simpler initially but create tight coupling that resists future changes. ATLAS needs to evolve rapidly.

**SQLite for task persistence vs. in-memory only**: Chose SQLite. The daemon must survive restarts without losing mission state. In-memory would be faster but fragile. SQLite is fast enough for task queue operations.

**Claude Code CLI per-step vs. persistent sessions**: Architecture supports both. One-shot calls (`claude -p`) for independent planning steps; persistent sessions for multi-turn reasoning within complex tasks. The Claude Code bridge component abstracts this choice.

## 9. Open Questions

- What is the optimal prompt structure for goal decomposition? Needs prototyping with real goals.
- How should the reflection step balance thoroughness vs. speed? Every reflection is a Claude Code call with associated latency.
- Should the Task Queue Manager use a database-backed priority queue or an in-memory heap with periodic persistence? Depends on expected queue sizes.
- How to handle missions that span days? Context drift, environment changes, and stale plans become issues.
- What is the right concurrency model for the execution loop? asyncio, threading, or multiprocessing?
