# ATLAS Phase 3 — Manual Testing Plan

## Prerequisites

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Install in dev mode
pip install -e ".[dev]"

# 3. Set required API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 4. (Optional) For vector search tests
export VOYAGE_API_KEY="..."

# 5. Verify tests pass first
pytest tests/ -v
```

> **Tip:** To start fresh between test sections, delete `~/.atlas/` to reset database, logs, and config.

---

## Test 1: Basic Goal Execution

**What it tests:** Core execution loop, task planning, skill invocation, audit logging, episodic memory.

```bash
# Simple goal — should plan, execute, and complete
atlas goal "list all Python files in the current directory"

# Verify audit log was written
sqlite3 ~/.atlas/data/atlas.db "SELECT action_type, outcome FROM audit_log ORDER BY timestamp DESC LIMIT 5;"

# Verify episode was recorded
sqlite3 ~/.atlas/data/atlas.db "SELECT trigger_text, outcome FROM episodes ORDER BY timestamp DESC LIMIT 1;"
```

**Expected:**
- Goal decomposes into 1+ tasks
- Tasks execute using seed skills (`file.search` or `shell.execute`)
- Mission completes with success status
- Audit log has entries for each action
- Episode recorded with goal text and outcome

---

## Test 2: Autonomy Levels

**What it tests:** Control plane autonomy enforcement.

```bash
# Observe mode — should plan but NOT execute
atlas goal "create a file called /tmp/atlas-test.txt" --autonomy observe

# Verify file was NOT created
ls /tmp/atlas-test.txt  # should not exist

# Suggest mode — should prompt for approval
atlas goal "create a file called /tmp/atlas-test.txt" --autonomy suggest
# When prompted, approve the action

# Act mode (default) — should execute within bounds
atlas goal "create a file called /tmp/atlas-test.txt"
```

**Expected:**
- `observe`: Plans tasks, logs them, does not execute
- `suggest`: Plans tasks, prompts for each action, executes on approval
- `act`: Plans and executes within configured allowed paths

---

## Test 3: Credential Vault

**What it tests:** Encrypted credential storage (Fernet + PBKDF2).

```bash
# Store a credential (will prompt for value and passphrase)
atlas vault set github token --value "ghp_test123" --passphrase "mypass"

# List credentials (values should NOT be shown)
atlas vault list

# Verify encryption in database (should be ciphertext, not plaintext)
sqlite3 ~/.atlas/data/atlas.db "SELECT service, key, encrypted_value FROM credentials;"

# Delete the credential
atlas vault delete github token

# Confirm deletion
atlas vault list
```

**Expected:**
- Credential stored with encrypted blob (not plaintext)
- `vault list` shows service/key pairs only
- `vault delete` removes the entry
- Database contains ciphertext, never plaintext values

---

## Test 4: Approval Rules

**What it tests:** Standing approval rule creation, matching, and enforcement.

```bash
# Add a rule: auto-allow low-risk file operations
atlas rules add --skill "file.*" --risk low --decision allow --description "Allow low-risk file ops"

# Add a rule: deny all shell commands
atlas rules add --skill "shell.*" --risk "*" --decision deny --description "Block shell commands"

# List rules
atlas rules list

# Test rule matching: this should auto-approve (matches file.* + low risk)
atlas goal "read the contents of pyproject.toml"

# Test rule matching: this should be denied (matches shell.*)
atlas goal "run the command: echo hello"

# Remove a rule (use rule_id from `rules list`)
atlas rules remove <rule_id>
```

**Expected:**
- Rules created with unique IDs
- `rules list` shows all active rules
- File operations auto-approved when matching allow rule
- Shell commands denied when matching deny rule
- Removed rules no longer apply

---

## Test 5: Trust Tracking & Recommendations

**What it tests:** Trust escalation/demotion system.

```bash
# Check initial trust state (should be empty)
atlas trust status

# Run multiple successful goals using the same skill
for i in $(seq 1 12); do
  atlas goal "search for the word 'import' in pyproject.toml" --auto-approve
done

# Check trust records (should show successes accumulating)
atlas trust status

# Check for escalation recommendations
atlas trust recommendations

# Accept a recommendation (if one was generated)
atlas trust accept <recommendation_id>

# Verify override was applied
atlas trust status
```

**Expected:**
- Trust records accumulate per-skill success/failure counts
- After 10 consecutive successes (default threshold), an escalation recommendation is created
- Accepting a recommendation applies an autonomy override to that skill
- `trust status` shows the override

---

## Test 6: Daemon Lifecycle

**What it tests:** Daemon start/stop/status, PID file management.

```bash
# Start daemon
atlas daemon start

# Check status (should show running + PID)
atlas daemon status

# Verify PID file
cat ~/.atlas/daemon.pid

# Stop daemon
atlas daemon stop

# Confirm stopped
atlas daemon status
```

**Expected:**
- `daemon start` forks background process, prints PID
- `daemon status` shows "running" with PID and uptime
- `daemon stop` sends shutdown signal
- After stop, status shows "not running"

---

## Test 7: Emergency Controls (Daemon Mode)

**What it tests:** Pause/resume/kill functionality.

```bash
# Start daemon
atlas daemon start

# Pause daemon
atlas daemon pause

# Check status (should show paused)
atlas daemon status

# Resume daemon
atlas daemon resume

# Submit a goal via CLI (daemon processes it)
atlas goal "list files in current directory"

# Kill a specific task (if one is running)
atlas daemon kill <task_id>

# Clean up
atlas daemon stop
```

**Expected:**
- `pause` stops new task acceptance; running tasks finish
- `resume` re-enables task acceptance
- `kill` cancels a specific running/queued task
- Status reflects paused/resumed state

---

## Test 8: Dashboard API (Daemon Mode)

**What it tests:** REST API endpoints exposed by the daemon.

```bash
# Create config to enable dashboard
mkdir -p ~/.atlas/config
cat > ~/.atlas/config/atlas.yaml << 'EOF'
webhook:
  enabled: true
  dashboard_enabled: true
  port: 8484
EOF

# Start daemon
atlas daemon start

# Test status endpoint
curl -s http://127.0.0.1:8484/api/status | python -m json.tool

# Test health endpoint
curl -s http://127.0.0.1:8484/api/health | python -m json.tool

# Test config endpoint
curl -s http://127.0.0.1:8484/api/config | python -m json.tool

# Test skills listing
curl -s http://127.0.0.1:8484/api/skills | python -m json.tool

# Submit a goal via API
curl -s -X POST http://127.0.0.1:8484/api/goal \
  -H "Content-Type: application/json" \
  -d '{"goal_text": "list Python files in the current directory"}' | python -m json.tool

# Check missions
curl -s http://127.0.0.1:8484/api/missions | python -m json.tool

# Check tasks
curl -s http://127.0.0.1:8484/api/tasks | python -m json.tool

# Check audit log
curl -s "http://127.0.0.1:8484/api/audit?limit=10" | python -m json.tool

# Check memory stats
curl -s http://127.0.0.1:8484/api/memory/stats | python -m json.tool

# Emergency controls via API
curl -s -X POST http://127.0.0.1:8484/api/emergency/pause | python -m json.tool
curl -s -X POST http://127.0.0.1:8484/api/emergency/resume | python -m json.tool

# Approval rules via API
curl -s http://127.0.0.1:8484/api/approvals/rules | python -m json.tool
curl -s -X POST http://127.0.0.1:8484/api/approvals/rules \
  -H "Content-Type: application/json" \
  -d '{"match_skill": "file.*", "match_risk": "low", "decision": "allow", "description": "API rule"}' | python -m json.tool

# Trust records via API
curl -s http://127.0.0.1:8484/api/trust/records | python -m json.tool
curl -s "http://127.0.0.1:8484/api/trust/recommendations?status=pending" | python -m json.tool

# Connectors
curl -s http://127.0.0.1:8484/api/connectors | python -m json.tool

# Clean up
atlas daemon stop
```

**Expected:**
- All endpoints return valid JSON
- `/api/status` shows uptime, paused state, active task
- `/api/health` reports subsystem health (database, skill_registry, memory, emergency)
- `/api/goal` accepts and processes goals asynchronously
- `/api/missions` and `/api/tasks` reflect submitted work
- Emergency endpoints change daemon state
- Approval rule CRUD works via API

---

## Test 9: Vector Search (Requires VOYAGE_API_KEY)

**What it tests:** Voyage AI embeddings, SQLite blob storage, hybrid FTS5+cosine scoring.

```bash
# Enable vector search
export VOYAGE_API_KEY="..."
cat > ~/.atlas/config/atlas.yaml << 'EOF'
memory:
  vector_search:
    enabled: true
    model: "voyage-3-lite"
    semantic_weight: 0.6
    keyword_weight: 0.4
EOF

# Run a few diverse goals to build up episodes
atlas goal "read the README.md file" --auto-approve
atlas goal "search for all test files" --auto-approve
atlas goal "list the contents of the src directory" --auto-approve

# Check that embeddings were stored
sqlite3 ~/.atlas/data/atlas.db "SELECT COUNT(*) FROM episode_embeddings;"

# Check memory stats via API (if dashboard enabled)
curl -s http://127.0.0.1:8484/api/memory/stats | python -m json.tool

# Run a goal that should benefit from semantic context
# (the system should retrieve relevant past episodes)
atlas goal "find Python source files" --auto-approve
```

**Expected:**
- Episodes get embedded via Voyage AI after each mission
- `episode_embeddings` table populated with vector blobs
- Subsequent goals use hybrid search (FTS keyword + cosine similarity) for context assembly
- Memory stats show non-zero `embedding_count`

---

## Test 10: Filesystem Watches & Reactive Rules

**What it tests:** Observation engine, filesystem monitoring, reactive goal triggering.

```bash
# Configure reactive mode
cat > ~/.atlas/config/atlas.yaml << 'EOF'
observation:
  filesystem_debounce_seconds: 2.0
  watches:
    - "./tests"
reactive:
  enabled: true
  rules:
    - name: "on-test-change"
      trigger:
        type: "filesystem"
        pattern: "test_*.py"
      goal: "Run pytest on the changed test file"
      cooldown: 60
webhook:
  enabled: true
  dashboard_enabled: true
EOF

# Start daemon (required for reactive mode)
atlas daemon start

# Add a watch via CLI
atlas watch add "./src"
atlas watch list

# Modify a test file to trigger reactive rule
echo "# trigger" >> tests/unit/test_example.py

# Wait a few seconds for debounce, then check if goal was triggered
sleep 5
curl -s http://127.0.0.1:8484/api/missions | python -m json.tool

# Clean up
git checkout tests/unit/test_example.py
atlas daemon stop
```

**Expected:**
- Watches registered and listed
- File modification detected by watchdog
- Reactive rule matches the event pattern
- Goal auto-submitted to daemon for execution
- Cooldown prevents re-triggering within 60 seconds

---

## Test 11: MCP Bridge

**What it tests:** MCP server tool discovery and skill registration.

```bash
# Configure an MCP server (example with a hypothetical server)
cat > ~/.atlas/config/atlas.yaml << 'EOF'
mcp:
  enabled: true
  servers:
    - name: "example-server"
      command: "npx"
      args: ["-y", "@example/mcp-server"]
EOF

# Start daemon
atlas daemon start

# Check that MCP tools were registered as skills
curl -s http://127.0.0.1:8484/api/skills | python -m json.tool
# Look for skills with IDs like "mcp.tool_name"

atlas daemon stop
```

**Expected:**
- MCP server started as subprocess
- Available tools discovered and registered as ATLAS skills
- Skills appear with `mcp.` prefix in skill registry

---

## Test 12: GitHub Webhook Integration

**What it tests:** Webhook endpoint, HMAC signature verification, event routing.

```bash
# Configure GitHub integration
cat > ~/.atlas/config/atlas.yaml << 'EOF'
webhook:
  enabled: true
  dashboard_enabled: true
  port: 8484
github:
  token: "ghp_..."
  owner: "jeremybrice"
  repo: "the-atlas"
  webhook_secret: "test-secret"
EOF

# Start daemon
atlas daemon start

# Send a simulated GitHub push event (without valid HMAC — should be rejected)
curl -s -X POST http://127.0.0.1:8484/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-Hub-Signature-256: sha256=invalid" \
  -d '{"ref": "refs/heads/main", "commits": []}' | python -m json.tool

# Should return 401 or signature mismatch error

atlas daemon stop
```

**Expected:**
- Webhook endpoint rejects requests with invalid HMAC signatures
- Valid webhooks parsed and routed to observation engine
- Events matched against reactive rules for auto-response

---

## Quick Smoke Test (All-in-One)

For a fast sanity check of the core system:

```bash
# Fresh start
rm -rf ~/.atlas

# Basic execution
atlas goal "list files in the current directory" --auto-approve

# Vault round-trip
atlas vault set test svc --value "val123" --passphrase "pass"
atlas vault list
atlas vault delete test svc

# Rules round-trip
atlas rules add --skill "file.*" --risk low --decision allow --description "test rule"
atlas rules list
RULE_ID=$(sqlite3 ~/.atlas/data/atlas.db "SELECT rule_id FROM approval_rules LIMIT 1;")
atlas rules remove "$RULE_ID"

# Trust check
atlas trust status

# Status
atlas status

echo "Smoke test complete."
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `ClaudeCodeUnavailableError` | Verify `ANTHROPIC_API_KEY` is set and valid |
| Vector search silently disabled | Check `VOYAGE_API_KEY` is set; check `~/.atlas/logs/atlas.log` for warnings |
| Daemon won't start | Check if PID file exists: `cat ~/.atlas/daemon.pid`; remove stale file if process is dead |
| Dashboard not responding | Verify `webhook.enabled` and `webhook.dashboard_enabled` are `true` in config |
| Reactive rules not firing | Check `reactive.enabled: true`, watches configured, daemon is running (not paused) |
| Permission denied on goal | Check `control.allowed_read_paths` / `allowed_write_paths` in config |
| Database locked | Ensure only one daemon instance is running; check for zombie processes |

---

## Notes

- All database state lives in `~/.atlas/data/atlas.db` (SQLite with WAL mode)
- Logs are JSON-formatted at `~/.atlas/logs/atlas.log`
- Delete `~/.atlas/` to fully reset between test sessions
- The `--auto-approve` flag bypasses approval prompts (useful for scripted testing)
- Daemon mode is required for: reactive rules, filesystem watches, dashboard API, webhook ingestion
