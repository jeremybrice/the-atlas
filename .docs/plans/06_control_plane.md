# Domain 6: Control Plane — Detailed Goals

## Primary Mission
Design the governance, safety, and observability layer that ensures ATLAS operates within defined boundaries, provides full transparency into agent behavior, and gives the user ultimate control over what the agent can and cannot do autonomously. The Control Plane is the trust layer: it's what makes it safe to let an autonomous agent run on your desktop.

## Goals

### G6.1: Autonomy Level Framework
Design a graduated autonomy model that defines what the agent can do without asking. Levels might include:

- **Level 0 — Observe Only**: Agent watches and logs but takes no actions. Good for initial deployment and trust-building.
- **Level 1 — Suggest**: Agent proposes actions but waits for explicit approval before executing. All proposals include reasoning.
- **Level 2 — Act Within Bounds**: Agent executes routine actions within predefined safe boundaries (read files, search, generate content) but pauses for approval on anything outside bounds (write files, send messages, modify external state).
- **Level 3 — Full Autonomy**: Agent executes all planned actions, only pausing for explicitly flagged high-risk operations.

The autonomy level should be configurable globally, per-domain, per-skill, and per-task. A user might say: "Level 3 for filesystem operations in my project directory, Level 1 for anything touching Jira, Level 0 for Slack."

### G6.2: Approval Workflow Engine
Design the system for human-in-the-loop approval. When the agent encounters an action that requires approval: it must pause execution cleanly (not lose state), present the proposed action with full context (what it wants to do, why, what the expected outcome is, what could go wrong), support multiple approval channels (terminal prompt, desktop notification, future Tauri UI), handle approval timeouts (what happens if the user doesn't respond?), and resume execution seamlessly after approval or gracefully handle rejection. Batch approval should be supported ("approve all pending filesystem writes for this task").

### G6.3: Audit Log System
Design comprehensive logging that captures everything the agent does. Every action, decision, observation, skill invocation, external API call, and error must be logged with: timestamp, the task/mission context, what was done, why (the reasoning that led to the action), the outcome, and any side effects. Logs must be: structured (queryable, not just text), tamper-evident (the agent can't silently modify its own logs), retained according to configurable policies, and exportable (for external analysis). The audit log is distinct from episodic memory; it's a compliance/debugging record, not a learning resource.

### G6.4: Safety Boundary Definitions
Design the rule system that defines what the agent is and isn't allowed to do. Boundaries include: filesystem boundaries (allowed paths, read vs. write), process boundaries (allowed commands, resource limits), network boundaries (allowed hosts/ports), external service boundaries (allowed operations per connector), data boundaries (sensitive files or directories that are off-limits), and temporal boundaries (operating hours, rate limits on actions per hour). Boundaries must be: declaratively defined (config files, not hardcoded), composable (multiple rule sets can combine), auditable (log when boundaries are checked and the result), and overridable per-task with explicit user approval.

### G6.5: Dashboard and Status API
Design the API surface that a future Tauri frontend (or any monitoring tool) would consume. This API must expose: current agent state (idle, planning, executing, waiting for approval), active task queue with status and progress, recent action history (last N actions with outcomes), pending approval requests, system health metrics (memory usage, process count, connection status), skill registry summary, and memory statistics. The API should be a local HTTP endpoint (or Unix socket) with structured JSON responses. It must be designed frontend-agnostically so that a Tauri app, a web dashboard, or even a simple CLI status command can consume it.

### G6.6: Emergency Controls
Design the mechanisms for immediate human intervention. The user must be able to: pause all agent activity instantly (no completing current action), kill a specific task without affecting others, revoke a skill's permissions immediately, roll back recent filesystem changes, and shut down the daemon cleanly (completing or checkpointing current work). Emergency controls must be accessible from: the terminal (kill signals, CLI commands), the future Tauri UI, and keyboard shortcuts / system tray. The system must be designed so that the agent cannot override or circumvent emergency controls under any circumstances.

### G6.7: Configuration Management
Design how all ATLAS configuration is stored, validated, and applied. Configuration includes: autonomy levels and boundary rules, connector credentials and settings, observation engine triggers and filters, skill registry metadata, memory retention policies, and system preferences. Configuration must be: human-readable (YAML or TOML, not binary), version-controlled (changes tracked, rollback possible), validated on load (schema validation, no silent corruption), hot-reloadable where possible (don't require daemon restart for config changes), and documented (every setting has a description and default).

### G6.8: Trust Escalation and Learning
Design how the agent earns more autonomy over time. As the agent successfully completes tasks at a given autonomy level, the Control Plane should: track success/failure rates per capability, suggest autonomy level increases for consistently safe operations, require explicit user approval for any autonomy escalation, and automatically reduce autonomy if failure rates increase. This creates a natural trust-building loop where the agent starts cautious and gradually earns more freedom.

## Cross-Domain Dependencies
- **Agent Core**: Core checks approval gates before every action. Core reports all decisions for audit logging. Core respects autonomy levels in planning.
- **Skill Engine**: Skill creation and modification require approval at lower autonomy levels. Skills declare their risk level, informing approval requirements.
- **Memory System**: Audit logs are separate from memory but may reference memory entries. Control Plane configuration persists across restarts.
- **Environment Interface**: Sandbox configuration comes from Control Plane boundaries. Environment actions are the primary subjects of safety checks.
- **Integration Layer**: External service interactions are high-risk actions subject to approval. Credential usage is audited.

## Key Constraints
- Emergency controls must ALWAYS work, even if other system components are failing
- The audit log must be append-only and tamper-resistant
- Configuration errors must fail safe (if config is invalid, agent reverts to most restrictive autonomy level)
- The approval workflow must not create a bottleneck that makes the agent useless (smart batching, sensible defaults)
- The Control Plane must be the first component initialized and the last shut down
- No action in any domain should be possible without passing through Control Plane checks
