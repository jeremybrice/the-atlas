# Mission Brief

**Playbook:** feature-build
**Design Doc:** docs/plans/2026-03-13-phase3-stage-a.md
**Created:** 2026-03-13

## Requirements Summary

1. **TrustRecord dataclass + TrustConfig** — Add `TrustRecord` to `contracts/types.py`, `TrustConfig` to `config.py`, trust section to `default.yaml`
2. **trust_records SQLite table** — Add table to `DatabaseStore._create_tables()` in `memory/store.py`
3. **TrustTracker core logic** — New `control/trust.py` with outcome recording, escalation suggestion (N consecutive successes), auto-demotion (failure spike), SQLite persistence
4. **PolicyEngine per-skill overrides** — Extend `control/policy.py` to accept `skill_overrides` dict, resolve per-skill autonomy before evaluating risk
5. **credentials SQLite table** — Add table to `DatabaseStore._create_tables()`
6. **CredentialVault** — New `integrations/vault.py` with Fernet encryption, PBKDF2 key derivation, CRUD API (store/get/delete/list)
7. **Vault CLI commands** — Add `atlas vault set/list/delete` commands to `cli.py`
8. **MCPConfig + EventType.WEBHOOK** — Add `MCPConfig` to `config.py`, `WEBHOOK` to `EventType` enum, mcp section to `default.yaml`
9. **MCPBridge + MCPSkillAdapter** — New `integrations/mcp.py` that connects to MCP servers, wraps tools as ATLAS skills with `risk_level=HIGH`, registers in `SkillRegistry`
10. **cryptography dependency** — Add to `pyproject.toml`
11. **Integration test** — Trust + Policy + Vault wired together end-to-end in `tests/integration/test_trust_vault_integration.py`
12. **Full suite validation** — All tests pass, ruff clean

## Key Files

- `src/atlas/contracts/types.py` — Shared types, add TrustRecord and EventType.WEBHOOK
- `src/atlas/config.py` — Config dataclasses, add TrustConfig and MCPConfig
- `src/atlas/control/policy.py` — Policy engine, extend with skill_overrides
- `src/atlas/memory/store.py` — DB schema, add trust_records and credentials tables
- `src/atlas/cli.py` — CLI commands, add vault group
- `src/atlas/skills/registry.py` — Skill registry, consumed by MCPBridge
- `src/atlas/contracts/errors.py` — Error hierarchy (reference)
- `pyproject.toml` — Dependencies
- `config/default.yaml` — Default configuration

## Test Command

`pytest tests/ -v`

## Developer Callouts

None specified. Follow CLAUDE.md conventions:
- Python 3.12+ with `str | None` syntax
- No `from __future__ import annotations` in new files
- src layout imports: `from atlas.x import Y`
- Errors extend `RetriableError` or `FatalError`
- Mock only `ClaudeCodeBridge`, use real SQLite with `tmp_path`

## Success Criteria

- All 12 tasks from the implementation plan are complete
- `TrustTracker` records outcomes and correctly triggers escalation/demotion suggestions
- `PolicyEngine` respects per-skill autonomy overrides
- `CredentialVault` encrypts/decrypts credentials with Fernet, persists to SQLite
- `MCPBridge` registers MCP tools as ATLAS skills
- CLI `atlas vault set/list/delete` commands work
- All new and existing tests pass (`pytest tests/ -v`)
- Lint clean (`ruff check src/ tests/`)
- Integration test demonstrates trust + policy + vault working together
