# ATLAS — Autonomous Tool-Learning Agent System
# Master Architecture Document

## Naming

- **Repository**: `clap`
- **Python package**: `atlas`
- **Project codename**: ATLAS (Autonomous Tool-Learning Agent System)

## Project Overview

ATLAS is an autonomous, self-improving desktop agent platform built on Claude Code CLI. It takes inspiration from The Forge plugin ecosystem but is a clean break — no backward compatibility with Forge data structures or plugin interfaces.

## Document Index

### Foundation
- **[PROJECT_VISION.md](./PROJECT_VISION.md)** — Shared project vision, core decisions, cross-domain interface contracts
- **[00_foundation_spec.md](./00_foundation_spec.md)** — Package structure, canonical interfaces, Phase 1 scope, error model, testing, deployment, observability. **Where domain plans differ from the Foundation Spec on cross-domain concerns, the Foundation Spec wins.**

### Domain Goals (Input Specifications)
- **[01_agent_core.md](./01_agent_core.md)** — Agent Core goals
- **[02_memory_system.md](./02_memory_system.md)** — Memory System goals
- **[03_skill_engine.md](./03_skill_engine.md)** — Skill Engine goals
- **[04_environment_interface.md](./04_environment_interface.md)** — Environment Interface goals
- **[05_integration_layer.md](./05_integration_layer.md)** — Integration Layer goals
- **[06_control_plane.md](./06_control_plane.md)** — Control Plane goals

### Architectural Plans (Design Output)
- **[01_agent_core_plan.md](./01_agent_core_plan.md)** — Agent Core architecture
- **[02_memory_system_plan.md](./02_memory_system_plan.md)** — Memory System architecture
- **[03_skill_engine_plan.md](./03_skill_engine_plan.md)** — Skill Engine architecture
- **[04_environment_interface_plan.md](./04_environment_interface_plan.md)** — Environment Interface architecture
- **[05_integration_layer_plan.md](./05_integration_layer_plan.md)** — Integration Layer architecture
- **[06_control_plane_plan.md](./06_control_plane_plan.md)** — Control Plane architecture

## Cross-Domain Integration Summary

### Data Flow
```
User Goal/Trigger
       │
       ▼
┌─────────────┐    checks    ┌──────────────┐
│ Agent Core  │◄────────────►│ Control Plane│
│ (Domain 1)  │    logs      │ (Domain 6)   │
└──────┬──────┘              └──────────────┘
       │
       ├──── reads/writes ──► Memory System (Domain 2)
       │
       ├──── invokes ───────► Skill Engine (Domain 3)
       │                          │
       │                          ├── executes via ──► Environment Interface (Domain 4)
       │                          │                         │
       │                          └── uses ────────► Integration Layer (Domain 5)
       │                                                    │
       └──── observes ──────► Environment Interface ◄───────┘
                              (observations flow back)
```

### Shared Communication Patterns
- **Synchronous**: Policy checks (Control Plane), capability queries (Skill Engine), state queries (Environment)
- **Asynchronous**: Episode recording (Memory), audit logging (Control Plane), skill invocation (Skill Engine)
- **Event-Driven**: Observation events (Environment → Core), external events (Integration → Environment → Core)

### Unified Phasing Strategy

**Phase 1 — MVP (Prove the Loop)**
Goal: A working planning-execution-reflection loop with basic skills. See [Foundation Spec Section 5](./00_foundation_spec.md#5-phase-1-mvp-scope) for the definitive Phase 1 scope.
- Agent Core: Single-threaded execution, linear task decomposition, CLI goal input
- Memory: Working memory + episodic (SQLite/FTS5), basic context assembly
- Skills: Registry, invocation runtime, 4 seed skills (file.read, file.write, file.search, shell.execute), no self-authoring
- Environment: Filesystem + process providers, Claude Code one-shot bridge
- Integration: None (deferred to Phase 2)
- Control: Basic autonomy levels, terminal approval, audit logging

**Phase 2 — Full (Complete the Vision)**
Goal: Full autonomy with self-improvement and comprehensive integrations.
- Agent Core: Reactive mode, task graphs, parallel tasks, replanning
- Memory: All four tiers, pattern extraction, purpose-aware context assembly
- Skills: Skill Forge (autonomous creation), workflow composer, skill evolution
- Environment: Observation engine, Claude Code sessions, sandboxing
- Integration: Read-write connectors, MCP Bridge, Event Bridge, entity mapping
- Control: Hash chain audit, batch/standing approvals, trust escalation, dashboard API

**Phase 3 — Advanced (Push Boundaries)**
Goal: Cutting-edge autonomous capabilities.
- Agent Core: Multi-agent, predictive planning, cross-mission learning
- Memory: Vector search, causal reasoning, memory consolidation
- Skills: Self-improving workflows, skill marketplace, natural language invocation
- Environment: Browser automation, screen capture, predictive resources
- Integration: ATLAS as MCP server, auto-discovery, agent-authored connectors
- Control: Tauri UI, natural language policies, multi-user, audit analytics
