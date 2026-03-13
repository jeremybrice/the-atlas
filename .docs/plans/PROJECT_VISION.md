# Project Codename: ATLAS (Autonomous Tool-Learning Agent System)

## Vision Statement

ATLAS is an autonomous, self-improving desktop agent platform built on top of Claude Code CLI. It is the successor to "The Forge" plugin ecosystem, absorbing and evolving its capabilities into a unified autonomous agent that can observe, learn, plan, execute, and improve itself over time.

## Core Architectural Decisions

- **LLM Interface**: Claude Code CLI (subprocess invocations via `claude -p` and interactive mode). No direct API calls. Leverages existing Claude subscription.
- **Primary Language**: Python (inheriting from forge-lib foundation)
- **Storage**: Local-first (SQLite + JSON + Markdown files)
- **Runtime Model**: Long-running daemon process with clean internal API (HTTP/Unix socket)
- **Future Frontend**: Tauri desktop shell (out of scope for this phase; architecture must expose clean APIs for it)
- **Predecessor**: The Forge ecosystem (7 plugins, forge-lib Python data layer, 15 JSON schemas, 124 tests, Tauri desktop shell concept)

## Operating Modes

ATLAS operates in two concurrent modes:

1. **Reactive/Continuous Mode**: Background daemon watches for triggers (file changes, scheduled times, external events). Evaluates triggers against rules and acts within predefined boundaries autonomously.

2. **Proactive/Mission Mode**: User assigns a goal. Agent decomposes into tasks, plans execution, works through steps, and reports back. Multi-step, multi-tool, potentially long-running.

Both modes share the same task queue, priority system, memory, and skill engine.

## Six Architectural Domains

The system is divided into six domains. Each domain is a distinct architectural concern with defined interfaces to the others. All six must compose into a coherent whole.

### Domain 1: Agent Core
The central orchestration layer. Receives goals/triggers, decomposes them into tasks, manages the planning-execution-reflection loop, coordinates with all other domains. Owns the task queue and priority system.

### Domain 2: Memory System
Persistent knowledge layer across sessions. Stores episodic memory (what happened), semantic memory (what the agent knows), working memory (current context), and procedural memory (how to do things). Provides retrieval interfaces for the Agent Core and Skill Engine.

### Domain 3: Skill Engine
Discovery, invocation, chaining, and self-authoring of skills. Absorbs existing Forge plugins as seed skills. Can create new skills when capability gaps are identified. Owns the skill registry, skill lifecycle, and skill testing/validation.

### Domain 4: Environment Interface
The agent's "hands and eyes." Manages all interactions with the desktop, filesystem, terminal, browser, APIs, and external services. Provides a unified abstraction layer so the Agent Core doesn't need to know the specifics of each environment capability.

### Domain 5: Integration Layer
Bridges to external systems: MCP servers, Forge plugin migration path, Jira, Slack, Google Drive, and other services. Manages authentication, connection lifecycle, and data translation between external formats and ATLAS internal representations.

### Domain 6: Control Plane
Safety, observability, and human-in-the-loop governance. Defines approval workflows, autonomy boundaries, audit logging, and the dashboard API that a future Tauri frontend would consume. Ensures the agent operates within defined guardrails.

## Cross-Domain Interface Contracts

These are the critical integration points that every domain plan must address:

- **Agent Core ↔ Memory System**: Core writes events/decisions to memory; reads context/history for planning. Memory provides relevance-ranked retrieval.
- **Agent Core ↔ Skill Engine**: Core requests skill execution; Skill Engine returns results. Core identifies capability gaps; Skill Engine attempts to fill them.
- **Agent Core ↔ Environment Interface**: Core issues environment actions (read file, run command, open URL); Environment executes and returns observations.
- **Agent Core ↔ Control Plane**: Core checks approval requirements before acting; Control Plane enforces boundaries and logs all actions.
- **Skill Engine ↔ Memory System**: Skills read/write to memory. Procedural memory IS the skill registry. Skill authoring reads past attempts from episodic memory.
- **Skill Engine ↔ Environment Interface**: Skills execute through environment capabilities. New skill authoring requires environment access for testing.
- **Integration Layer ↔ Environment Interface**: External service calls route through Environment Interface for unified logging and rate limiting.
- **Integration Layer ↔ Memory System**: Credentials, connection state, and external entity mappings persist in memory.
- **Control Plane ↔ All Domains**: Every domain emits events to Control Plane for audit. Control Plane can pause/block any domain's operations.

## Forge Migration Context

The existing Forge ecosystem includes:
- **forge-lib**: Python CLI data layer (SQLite-backed, JSON schemas)
- **7 Plugins**: product-forge-local, slack-inbox-scanner, jira-activity-scanner, skill-creator, cognitive-forge, working-memory-extractor, notion-writer
- **15 JSON Schemas**: Defining data structures across plugins
- **124 Tests**: Existing test coverage
- **Tauri Shell**: Desktop app concept (partially built)
- **Skill-Creator Framework**: For building, testing, and packaging Claude skills

ATLAS should provide a migration path that preserves the value of existing plugins while evolving them into native ATLAS skills.

## Deliverable for Each Domain

Each domain plan should include:
1. **Architecture Overview**: High-level component diagram and narrative
2. **Component Breakdown**: Each major component, its responsibility, and its interfaces
3. **Data Models**: Key entities, their relationships, and storage approach
4. **Interface Contracts**: Detailed API/protocol definitions for cross-domain communication
5. **State Management**: How state flows through the domain, lifecycle of key entities
6. **Design Patterns**: Architectural patterns employed and why
7. **Phased Rollout**: How this domain gets built incrementally (Phase 1 = MVP, Phase 2 = Full, Phase 3 = Advanced)
8. **Key Tradeoffs**: Decisions made and alternatives considered
9. **Open Questions**: Unresolved architectural decisions that need further investigation
