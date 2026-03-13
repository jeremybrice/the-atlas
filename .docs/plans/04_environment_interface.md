# Domain 4: Environment Interface — Detailed Goals

## Primary Mission
Design the abstraction layer that gives ATLAS its "hands and eyes." The Environment Interface manages all interactions between the agent and the outside world: reading and writing files, executing terminal commands, observing system state, interacting with browsers, and monitoring desktop activity. It provides a unified, safe, auditable interface so the Agent Core and Skills don't need to know the specifics of each environment capability.

## Goals

### G4.1: Unified Environment Abstraction
Design a single interface through which all environment interactions flow, regardless of the underlying mechanism. The abstraction must support: filesystem operations (read, write, create, delete, watch), process execution (run commands, manage long-running processes, capture output), system observation (CPU/memory usage, running processes, network state), desktop interaction (window management, notifications, clipboard), and network requests (HTTP calls, WebSocket connections, API interactions). Each capability category should be a pluggable provider behind the unified interface, allowing new environment capabilities to be added without modifying the Agent Core.

### G4.2: Observation Engine
Design the system that passively monitors the environment and generates observations. This is the "eyes" component. The Observation Engine watches for: filesystem changes (new/modified/deleted files in watched directories), process events (services starting/stopping, errors in logs), scheduled time events (cron-like triggers), and external signals (webhooks, file drops, IPC messages). Observations are structured events that flow to the Agent Core's reactive processing pipeline. The engine must be configurable (what to watch, how often, what thresholds trigger events) and efficient (low CPU/memory overhead when idle).

### G4.3: Action Execution Layer
Design how the agent actually performs actions in the environment. This is the "hands" component. Every action must be: validated before execution (does the agent have permission? are preconditions met?), executed with appropriate isolation (sandboxing where possible), monitored during execution (timeout detection, resource usage tracking), captured in full (stdin, stdout, stderr, exit codes, side effects), and reversible where possible (undo capability for filesystem changes). The execution layer must handle both synchronous (run command, wait for result) and asynchronous (start process, monitor in background) operations.

### G4.4: Filesystem Workspace Management
Design how ATLAS manages its working directories and file access. The agent needs: a dedicated workspace directory structure (for projects, temp files, skill outputs), a clear model for accessing user files (read-only by default, write with permission), file locking to prevent concurrent modification conflicts, and a virtual filesystem view that the Agent Core can reason about ("what files are relevant to my current task?"). The workspace must be organized and self-cleaning (temp files don't accumulate indefinitely).

### G4.5: Process and Session Management
Design how ATLAS manages external processes. This includes: spawning and monitoring child processes (build tools, test runners, servers), managing Claude Code CLI sessions (persistent interactive sessions vs. one-shot calls), tracking long-running background processes across daemon restarts, and providing a process table that the Agent Core can query ("what's currently running?"). Claude Code CLI is the most important process to manage; the interface must handle its specific quirks (context window limits, session timeouts, rate limiting).

### G4.6: Environment State Model
Design a structured representation of the current environment state that the Agent Core can use for planning. This includes: working directory contents and structure, running processes and their health, available system resources (disk space, memory), network connectivity status, installed tools and their versions, and active Claude Code sessions. This state model is what gets injected into Claude Code prompts as environmental context. It must be lightweight (quick to generate) and informative (enough detail for good planning decisions).

### G4.7: Safety Sandbox
Design isolation boundaries for environment actions. Not all actions should have full system access. The sandbox model must define: which filesystem paths are accessible (and which are read-only vs. read-write), which commands can be executed without approval, resource limits (max memory, max disk usage, max execution time), and network access restrictions (which hosts/ports are allowed). The sandbox configuration should be adjustable per-skill and per-task, with the Control Plane providing governance.

## Cross-Domain Dependencies
- **Agent Core**: Issues action requests, receives observations and state. Core relies on environment state model for planning.
- **Skill Engine**: Skills execute through environment capabilities. Skill testing requires sandboxed environment access.
- **Memory System**: Environment observations are written to episodic memory. Environment state changes trigger memory updates.
- **Integration Layer**: External API calls route through the network request capability. Integration layer may register its own observation sources.
- **Control Plane**: Every environment action is logged. Sandbox configuration comes from Control Plane. High-risk actions require approval.

## Key Constraints
- Must run on macOS and Linux (primary development environments)
- Claude Code CLI integration must handle its specific UX patterns (interactive mode, slash commands, session management)
- Filesystem watching must be efficient (inotify/FSEvents, not polling)
- Process management must be robust across daemon restarts (orphan process detection)
- The observation engine must not generate excessive noise (smart filtering and debouncing)
- All environment interactions must be deterministically replayable from logs (for debugging)
