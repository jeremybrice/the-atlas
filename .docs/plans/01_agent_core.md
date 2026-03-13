# Domain 1: Agent Core — Detailed Goals

## Primary Mission
Design the central orchestration layer that serves as the "brain" of ATLAS. The Agent Core receives inputs (user goals, system triggers, skill results, environment observations), maintains the planning-execution-reflection loop, and coordinates all other domains to accomplish tasks autonomously.

## Goals

### G1.1: Task Lifecycle Management
Design a complete task lifecycle from inception to completion. Tasks originate from two sources: user-assigned missions (Proactive Mode) and system triggers (Reactive Mode). The core must decompose high-level goals into executable task trees, manage dependencies between tasks, handle failures and retries, and track progress. Tasks must be serializable so they survive daemon restarts.

### G1.2: Planning-Execution-Reflection Loop
Design the core reasoning loop that drives autonomous behavior. The agent must be able to: assess its current state and goals, form a plan of action, execute steps via skills and environment actions, observe results, reflect on whether the plan is working, and adapt. This loop must be interruptible (for human approval gates) and resumable. It must handle both fast tasks (seconds) and long-running missions (hours/days).

### G1.3: Task Queue and Priority System
Design a unified task queue that both operating modes feed into. Reactive triggers create tasks that enter the queue alongside mission-decomposed tasks. The priority system must handle: urgency (time-sensitive triggers), importance (user-assigned mission priority), dependencies (task B blocked on task A), and resource conflicts (two tasks wanting the same environment resource). The queue must support preemption for critical triggers.

### G1.4: Claude Code CLI Integration
Design the interface between the Agent Core and Claude Code CLI. Every reasoning step (planning, reflection, skill authoring) goes through Claude Code. The architecture must handle: session management (when to use persistent sessions vs. one-shot calls), context window management (what history/memory to inject into each call), prompt construction (assembling system prompts, memory context, task state, and instructions), and response parsing (extracting structured decisions from Claude's output).

### G1.5: Goal Decomposition Engine
Design how high-level user goals get broken into executable steps. This is not just a single LLM call; it must handle iterative refinement as the agent learns more during execution. The decomposition must produce a task graph (not just a linear list) that captures parallelism opportunities and conditional branches. The engine must know what skills are available (via Skill Engine) to ground decomposition in actual capabilities.

### G1.6: Inter-Domain Coordination Protocol
Design the protocol by which Agent Core communicates with all five other domains. This includes request/response patterns, event emission, error propagation, and timeout handling. The protocol must be consistent across domains so the core doesn't need domain-specific integration logic. Consider whether this is synchronous (function calls), asynchronous (message queue), or a mix.

## Cross-Domain Dependencies
- **Memory System**: Core reads context for planning, writes decisions and outcomes for learning
- **Skill Engine**: Core requests skill execution, receives results, identifies capability gaps
- **Environment Interface**: Core issues environment actions, receives observations
- **Control Plane**: Core checks approval gates before executing, reports all actions
- **Integration Layer**: Core may trigger external service interactions via skills that use integrations

## Key Constraints
- All LLM reasoning goes through Claude Code CLI, not direct API calls
- Must support graceful degradation if Claude Code is unavailable or rate-limited
- Task state must be durable across daemon restarts
- Must not create tight coupling to any specific LLM prompt format (prompts will evolve)
