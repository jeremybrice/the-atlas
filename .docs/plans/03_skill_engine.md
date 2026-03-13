# Domain 3: Skill Engine — Detailed Goals

## Primary Mission
Design the capability layer that gives ATLAS its ability to actually do things. The Skill Engine manages the full lifecycle of skills: discovering what's available, invoking skills to accomplish tasks, chaining multiple skills into workflows, and critically, authoring brand-new skills when the agent identifies a capability gap. This is the domain that makes ATLAS self-improving.

## Goals

### G3.1: Skill Abstraction Model
Design a universal skill definition that can represent anything from a simple file operation to a complex multi-step workflow. Every skill must have: a unique identifier, a natural language description (so the Agent Core and Claude Code can reason about when to use it), a typed input/output schema, preconditions (what must be true for this skill to work), postconditions (what should be true after successful execution), resource requirements (what environment capabilities it needs), and versioning (skills evolve over time). This model must be expressive enough to absorb the existing 7 Forge plugins without loss of functionality.

### G3.2: Skill Registry and Discovery
Design the central registry where all available skills are cataloged. The Agent Core must be able to query: "what skills can accomplish goal X?", "what skills operate on resource type Y?", and "what skills are available given current environment state Z?" The registry must support dynamic registration (new skills added at runtime), tagging and categorization, capability-based search (not just name matching), and dependency tracking (skill A requires skill B).

### G3.3: Skill Invocation Runtime
Design how skills are actually executed. Skills may be: Python functions (inherited from forge-lib), Claude Code CLI calls (LLM-powered skills that reason through problems), shell commands or scripts, workflow compositions (skill A then skill B then skill C), or hybrid (some steps are code, some are LLM reasoning). The runtime must handle: parameter validation against input schemas, timeout management, error handling and retry logic, output capture and validation against output schemas, and resource locking (if two skills want the same file).

### G3.4: Skill Chaining and Workflow Composition
Design how multiple skills compose into workflows. The Agent Core's goal decomposition produces task graphs; the Skill Engine must map those to skill chains. This includes: sequential composition (output of skill A feeds input of skill B), parallel execution (skills A and B run concurrently), conditional branching (if skill A returns X, run skill B; else run skill C), error recovery (if skill A fails, try alternative skill D), and data transformation between skills (skill A outputs format X, skill B expects format Y).

### G3.5: Self-Authoring — Autonomous Skill Creation
This is the crown jewel. Design how ATLAS creates new skills when it identifies a gap. The flow is: Agent Core attempts a task, discovers no existing skill can handle a step, requests Skill Engine to create one. The Skill Engine then: analyzes the requirement, searches episodic memory for similar past attempts, drafts a skill definition (description, schema, implementation), generates implementation code, tests the skill against expected behavior, validates the skill meets the original requirement, registers it in the skill registry, and writes the authoring episode to memory for future learning. This must leverage the existing skill-creator framework as a foundation. The agent should be able to author skills in Python, shell scripts, or as Claude Code prompt templates.

### G3.6: Skill Evolution and Improvement
Design how skills improve over time. After each invocation, the Skill Engine should: record performance metrics (success/failure, execution time, resource usage), compare against historical performance, identify degradation or improvement opportunities, and optionally trigger skill revision (a lighter-weight version of skill creation that modifies an existing skill). Skills should have maturity levels: draft (just authored, untested in production), stable (proven track record), and deprecated (superseded by a better skill).

### G3.7: Forge Plugin Migration
Design the specific migration path for absorbing the 7 existing Forge plugins into the ATLAS skill model. Each plugin has its own CLI entry point, forge-lib database interactions, and JSON schemas. The migration must preserve: existing functionality, test coverage (124 tests), and data in forge-lib databases. Ideally, migrated skills should be immediately usable by the Agent Core without manual reconfiguration.

## Cross-Domain Dependencies
- **Agent Core**: Primary consumer. Requests skill execution, reports capability gaps, receives results.
- **Memory System**: Procedural memory is the skill registry's knowledge layer. Episodic memory of past skill executions informs improvement. Semantic memory provides context for skill authoring.
- **Environment Interface**: Skills execute through environment capabilities. Skill authoring requires environment access for testing.
- **Integration Layer**: Some skills wrap external service interactions. Integration credentials and connection state must be accessible.
- **Control Plane**: Skill creation and modification are high-impact actions that may require approval. All skill executions are auditable.

## Key Constraints
- Skills must be self-contained and testable in isolation
- Skill authoring must not require human intervention for simple capabilities (but must escalate for complex or dangerous ones)
- The skill model must be extensible without breaking existing skills
- Performance: skill discovery and invocation overhead must be minimal (sub-second for registry queries)
- Self-authored skills must include generated tests (learned from skill-creator framework patterns)
