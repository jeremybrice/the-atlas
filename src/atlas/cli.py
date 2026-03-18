"""ATLAS CLI — command-line interface for the agent."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import click

from atlas.config import load_config
from atlas.contracts.types import AutonomyLevel, DaemonCommand
from atlas.control.approval import ApprovalWorkflow
from atlas.control.approval_rules import ApprovalRuleStore
from atlas.control.audit import AuditLogger
from atlas.control.emergency import EmergencyController
from atlas.control.policy import PolicyEngine
from atlas.control.trust import TrustTracker
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import (
    Mission,
    parse_task_plan,
    PLANNING_PROMPT_TEMPLATE,
    PLANNING_SYSTEM_PROMPT,
)
from atlas.daemon.loop import DaemonLoop
from atlas.daemon.manager import PidFile
from atlas.daemon.protocol import DaemonSocketClient
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.retrieval import ContextAssembler
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.observation.engine import ObservationEngine
from atlas.observation.router import EventRouter, ReactiveRule
from atlas.skills.forge import SkillForge
from atlas.integrations.mcp import MCPBridge
from atlas.skills.loader import load_skills_from_directory
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


def _ensure_data_dir() -> Path:
    data_dir = Path.home() / ".atlas"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "config").mkdir(exist_ok=True)
    (data_dir / "data").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    (data_dir / "skills").mkdir(exist_ok=True)
    return data_dir


def _setup_logging(data_dir: Path, level: str = "INFO") -> None:
    log_file = data_dir / "logs" / "atlas.log"
    log_fmt = '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'

    # File handler: everything
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_fmt))

    # Console handler: only warnings and above
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(log_fmt))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[file_handler, console_handler],
    )

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _load_config():
    """Load config with user override support."""
    user_config = Path.home() / ".atlas" / "config" / "atlas.yaml"
    override = str(user_config) if user_config.exists() else None
    return load_config(override)


@click.group()
def main():
    """ATLAS — Autonomous Tool-Learning Agent System"""
    pass


@main.command()
@click.argument("goal_text")
@click.option(
    "--autonomy",
    type=click.Choice(["observe", "suggest", "act"]),
    default="act",
    help="Autonomy level",
)
@click.option(
    "--auto-approve", is_flag=True, help="Auto-approve all actions (for testing)"
)
def goal(goal_text: str, autonomy: str, auto_approve: bool):
    """Submit a goal for ATLAS to accomplish."""
    config = _load_config()
    _ensure_data_dir()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))

    # If daemon is running, forward via socket
    if pid_file.is_running():
        socket_path = str(Path(config.daemon.socket_path).expanduser())
        click.echo("[daemon] Forwarding goal to running daemon...")
        result = asyncio.run(_forward_goal(socket_path, goal_text))
        if result.get("status") == "ok":
            click.echo(f"[daemon] Goal accepted: {result.get('payload', {})}")
        else:
            click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)
        return

    # No daemon — run inline
    asyncio.run(_run_goal(goal_text, autonomy, auto_approve))


async def _forward_goal(socket_path: str, goal_text: str) -> dict:
    client = DaemonSocketClient(socket_path)
    return await client.send(
        DaemonCommand(command="goal", payload={"goal_text": goal_text})
    )


async def _run_goal(goal_text: str, autonomy: str, auto_approve: bool) -> None:
    data_dir = _ensure_data_dir()
    config = _load_config()
    _setup_logging(data_dir, config.log_level)

    # Map CLI autonomy flag
    autonomy_map = {
        "observe": AutonomyLevel.OBSERVE,
        "suggest": AutonomyLevel.SUGGEST,
        "act": AutonomyLevel.ACT_WITHIN_BOUNDS,
    }
    autonomy_level = autonomy_map[autonomy]

    # Initialize components
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(Path.cwd()))
    proc = ProcessProvider()
    claude = ClaudeCodeBridge()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=claude)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)

    # Load custom skills
    custom_dir = str(Path(config.skills.custom_skills_dir).expanduser())
    loaded = load_skills_from_directory(custom_dir, registry)
    if loaded:
        click.echo(f"[skills] Loaded {loaded} custom skill(s)")

    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=autonomy_level)
    audit = AuditLogger(db=db.db)
    await audit.initialize()

    # Initialize control plane completion components
    emergency = EmergencyController()
    rule_store = ApprovalRuleStore(db)
    trust_tracker = TrustTracker(
        db=db,
        escalation_threshold=config.trust.escalation_threshold,
        demotion_failure_count=config.trust.demotion_failure_count,
        demotion_window_size=config.trust.demotion_window_size,
    )
    approval = ApprovalWorkflow(auto_approve=auto_approve, rule_store=rule_store)

    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    # Initialize vector search components if enabled
    context_assembler = ContextAssembler()
    vs_embedding_provider = None
    vs_vector_store = None

    if config.memory.vector_search.enabled:
        try:
            from atlas.memory.embeddings import EmbeddingProvider
            from atlas.memory.migration import VectorMigration
            from atlas.memory.vector_store import VectorStore

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise ValueError("VOYAGE_API_KEY environment variable not set")

            vs_embedding_provider = EmbeddingProvider(
                api_key=api_key,
                model=config.memory.vector_search.model,
            )
            vs_vector_store = VectorStore(db, model=config.memory.vector_search.model)

            # Update episodic store with embedding components
            episodic = EpisodicMemoryStore(
                db,
                embedding_provider=vs_embedding_provider,
                vector_store=vs_vector_store,
            )

            # Run migration if needed
            migration = VectorMigration(
                db, episodic, vs_vector_store, vs_embedding_provider
            )
            if not await migration.is_complete():
                click.echo("[vector-search] Migrating existing episodes...")
                count = await migration.run()
                if count:
                    click.echo(f"[vector-search] Embedded {count} episodes")

            click.echo("[vector-search] Semantic search enabled")
        except Exception as e:
            vs_embedding_provider = None
            vs_vector_store = None
            click.echo(f"[vector-search] Disabled: {e}", err=True)

    # Initialize forge if enabled
    forge = None
    if config.skills.forge_enabled:
        forge = SkillForge(
            registry=registry,
            claude_bridge=claude,
            skills_dir=custom_dir,
            workspace=str(Path.cwd()),
            max_retries=config.skills.forge_max_retries,
        )

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        forge=forge,
        context_assembler=context_assembler,
        embedding_provider=vs_embedding_provider,
        vector_store=vs_vector_store,
        search_limit=config.memory.vector_search.search_limit,
        semantic_weight=config.memory.vector_search.semantic_weight,
        keyword_weight=config.memory.vector_search.keyword_weight,
        emergency_controller=emergency,
        trust_tracker=trust_tracker,
    )

    try:
        # Plan the mission
        click.echo(f"[planning] Decomposing goal: {goal_text}")

        skills_desc = ", ".join(
            f"{s.skill_id} ({s.description})" for s in registry.list_all()
        )

        # Build project context from environment state + key config files
        state = env.get_state()
        context_parts = [
            f"workspace={state['workspace']['path']}",
            f"files={state['workspace']['entries']}",
            f"python={state['system']['python']}",
        ]
        # Include key config file contents for accurate planning
        for config_file in [
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "requirements.txt",
            "package.json",
            "Makefile",
        ]:
            try:
                content = fs.read(config_file)
                context_parts.append(f"{config_file}:\n{content}")
            except Exception:
                pass

        prompt = PLANNING_PROMPT_TEMPLATE.format(
            goal=goal_text, skills=skills_desc, context=" | ".join(context_parts)
        )

        try:
            response = await env.claude_oneshot(
                prompt, system_prompt=PLANNING_SYSTEM_PROMPT
            )
            tasks = parse_task_plan(response.content)
        except Exception as e:
            click.echo(f"[error] Planning failed: {e}", err=True)
            sys.exit(1)

        if not tasks:
            click.echo(
                "[error] Could not parse a task plan from Claude's response.", err=True
            )
            click.echo(
                f"[debug] Raw response ({len(response.content)} chars):", err=True
            )
            click.echo(repr(response.content[:500]), err=True)
            sys.exit(1)

        mission = Mission(goal_text=goal_text, tasks=tasks)
        click.echo(f"[planned] {len(tasks)} tasks")

        # Execute
        result = await loop.execute_mission(mission)

        # Report
        completed = sum(1 for t in result.tasks if t.status.value == "completed")
        total = len(result.tasks)
        if result.status.value == "completed":
            click.echo(
                f"[complete] {completed}/{total} tasks succeeded. Episode recorded."
            )
        else:
            click.echo(
                f"[failed] {completed}/{total} tasks succeeded. Mission failed.",
                err=True,
            )
            for t in result.tasks:
                if t.error:
                    click.echo(f"  - {t.description}: {t.error}", err=True)

        # Trust recommendations
        if hasattr(result, "trust_recommendations") and result.trust_recommendations:
            click.echo("\nTrust recommendations based on this mission:")
            for idx, rec in enumerate(result.trust_recommendations, 1):
                evidence = rec.evidence
                if rec.direction == "escalate":
                    detail = f"{evidence.get('consecutive_successes', '?')} consecutive successes"
                else:
                    detail = f"{evidence.get('failures', '?')} failures"
                click.echo(
                    f"  {idx}. {rec.skill_id} — {rec.direction} to {rec.recommended_level} ({detail})"
                )

            try:
                response = (
                    input("Accept recommendations? (y/n/select): ").strip().lower()
                )
            except (EOFError, KeyboardInterrupt):
                response = "n"

            if response in ("y", "yes"):
                for rec in result.trust_recommendations:
                    await trust_tracker.resolve_recommendation(
                        rec.recommendation_id, accepted=True
                    )
                click.echo("[trust] All recommendations accepted.")
            elif response == "select":
                for rec in result.trust_recommendations:
                    try:
                        choice = (
                            input(
                                f"  {rec.skill_id} → {rec.recommended_level}? (y/n): "
                            )
                            .strip()
                            .lower()
                        )
                    except (EOFError, KeyboardInterrupt):
                        choice = "n"
                    await trust_tracker.resolve_recommendation(
                        rec.recommendation_id, accepted=(choice in ("y", "yes"))
                    )
                click.echo("[trust] Recommendations resolved.")
            else:
                click.echo("[trust] Recommendations saved for later review.")
    finally:
        await db.close()


# --- Daemon commands ---


@main.group()
def daemon():
    """Manage the ATLAS background daemon."""
    pass


@daemon.command("start")
def daemon_start():
    """Start the ATLAS daemon in the background."""
    config = _load_config()
    data_dir = _ensure_data_dir()
    _setup_logging(data_dir, config.log_level)

    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if pid_file.is_running():
        click.echo(f"[daemon] Already running (PID {pid_file.read()})")
        return

    socket_path = str(Path(config.daemon.socket_path).expanduser())
    pid_path = str(Path(config.daemon.pid_file).expanduser())

    click.echo(f"[daemon] Starting... socket={socket_path}")

    # Fork to background
    pid = os.fork()
    if pid > 0:
        # Parent process
        click.echo(f"[daemon] Started (PID {pid})")
        return

    # Child process — become session leader
    os.setsid()
    asyncio.run(_run_daemon(socket_path, pid_path, config))


async def _run_daemon(socket_path: str, pid_path: str, config) -> None:
    """Run the daemon event loop."""
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(Path.cwd()))
    proc = ProcessProvider()
    claude = ClaudeCodeBridge()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=claude)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)

    # Load custom skills
    custom_dir = str(Path(config.skills.custom_skills_dir).expanduser())
    load_skills_from_directory(custom_dir, registry)

    runtime = InvocationRuntime(registry)
    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db=db.db)
    await audit.initialize()

    # Initialize control plane completion components
    emergency = EmergencyController()
    rule_store = ApprovalRuleStore(db)
    trust_tracker = TrustTracker(
        db=db,
        escalation_threshold=config.trust.escalation_threshold,
        demotion_failure_count=config.trust.demotion_failure_count,
        demotion_window_size=config.trust.demotion_window_size,
    )
    approval = ApprovalWorkflow(
        auto_approve=True, rule_store=rule_store
    )  # daemon mode auto-approves
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    # Initialize vector search components if enabled
    context_assembler = ContextAssembler()
    vs_embedding_provider = None
    vs_vector_store = None

    if config.memory.vector_search.enabled:
        try:
            from atlas.memory.embeddings import (
                EmbeddingProvider as DaemonEmbeddingProvider,
            )
            from atlas.memory.migration import VectorMigration as DaemonVectorMigration
            from atlas.memory.vector_store import VectorStore as DaemonVectorStore

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise ValueError("VOYAGE_API_KEY environment variable not set")

            vs_embedding_provider = DaemonEmbeddingProvider(
                api_key=api_key,
                model=config.memory.vector_search.model,
            )
            vs_vector_store = DaemonVectorStore(
                db, model=config.memory.vector_search.model
            )

            episodic = EpisodicMemoryStore(
                db,
                embedding_provider=vs_embedding_provider,
                vector_store=vs_vector_store,
            )

            migration = DaemonVectorMigration(
                db, episodic, vs_vector_store, vs_embedding_provider
            )
            if not await migration.is_complete():
                click.echo("[vector-search] Migrating existing episodes...")
                await migration.run()

            click.echo("[vector-search] Semantic search enabled (daemon)")
        except Exception as e:
            vs_embedding_provider = None
            vs_vector_store = None
            click.echo(f"[vector-search] Disabled in daemon: {e}", err=True)

    forge = None
    if config.skills.forge_enabled:
        forge = SkillForge(
            registry=registry,
            claude_bridge=claude,
            skills_dir=custom_dir,
            workspace=str(Path.cwd()),
            max_retries=config.skills.forge_max_retries,
        )

    # Initialize MCP bridge if enabled
    mcp_bridge = None
    if config.mcp.enabled:
        mcp_bridge = MCPBridge(registry=registry)

    execution_loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
        forge=forge,
        context_assembler=context_assembler,
        embedding_provider=vs_embedding_provider,
        vector_store=vs_vector_store,
        search_limit=config.memory.vector_search.search_limit,
        semantic_weight=config.memory.vector_search.semantic_weight,
        keyword_weight=config.memory.vector_search.keyword_weight,
        emergency_controller=emergency,
        trust_tracker=trust_tracker,
    )

    async def goal_executor(goal_text: str) -> dict:
        tasks = parse_task_plan(
            (
                await env.claude_oneshot(
                    PLANNING_PROMPT_TEMPLATE.format(
                        goal=goal_text,
                        skills=", ".join(s.skill_id for s in registry.list_all()),
                        context="daemon mode",
                    ),
                    system_prompt=PLANNING_SYSTEM_PROMPT,
                )
            ).content
        )
        if not tasks:
            return {"status": "error", "error": "Could not parse plan"}
        mission = Mission(goal_text=goal_text, tasks=tasks)
        result = await execution_loop.execute_mission(mission)
        return {"status": result.status.value, "tasks": len(result.tasks)}

    # Set up observation engine
    router = EventRouter()
    if config.reactive.enabled:
        from atlas.contracts.types import EventType

        for rule_cfg in config.reactive.rules:
            router.add_rule(
                ReactiveRule(
                    name=rule_cfg.get("name", "unnamed"),
                    event_type=EventType(
                        rule_cfg.get("trigger", {}).get("type", "filesystem")
                    ),
                    source_pattern=rule_cfg.get("trigger", {}).get("pattern", "*"),
                    goal_template=rule_cfg.get("goal", ""),
                    cooldown_seconds=rule_cfg.get(
                        "cooldown", config.reactive.cooldown_default_seconds
                    ),
                )
            )

    obs_engine = ObservationEngine(router=router, goal_handler=goal_executor)
    for watch_path in config.observation.watches:
        obs_engine.add_filesystem_watch(
            watch_path,
            ["*"],
            debounce_seconds=config.observation.filesystem_debounce_seconds,
        )

    await obs_engine.start()

    # Set up webhook + dashboard HTTP server if enabled
    http_app = None
    if config.webhook.enabled:
        from atlas.integrations.event_bridge import EventBridge
        from atlas.integrations.webhook import WebhookServer
        from atlas.integrations.dashboard import DashboardServer

        event_bridge = EventBridge()

        # Register GitHub event parser if configured
        if config.github.token:
            from atlas.integrations.connectors.github import GitHubConnector

            github_connector = GitHubConnector(
                token=config.github.token,
                owner=config.github.owner,
                repo=config.github.repo,
            )
            await github_connector.authenticate()
            event_bridge.register_parser("github", github_connector.get_event_parser())

        webhook_server = WebhookServer(
            event_bridge=event_bridge,
            event_callback=obs_engine.on_event,
            webhook_path_prefix=config.webhook.webhook_path_prefix,
            secrets=config.webhook.secrets,
        )
        http_app = webhook_server.create_app()

        if config.webhook.dashboard_enabled:
            dashboard_server = DashboardServer(
                db=db,
                audit=audit,
                registry=registry,
                goal_handler=goal_executor,
                config=config,
                emergency_controller=emergency,
                approval_rule_store=rule_store,
                trust_tracker=trust_tracker,
            )
            dashboard_app = dashboard_server.create_app()
            for resource in dashboard_app.router.resources():
                for route in resource:
                    http_app.router.add_route(
                        route.method, resource.canonical, route.handler
                    )

    daemon_loop = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=goal_executor,
        mcp_bridge=mcp_bridge,
        mcp_servers=config.mcp.servers,
        http_app=http_app,
        http_host=config.webhook.host,
        http_port=config.webhook.port,
        emergency_controller=emergency,
    )

    try:
        await daemon_loop.start()
    finally:
        await obs_engine.stop()
        await db.close()


@daemon.command("stop")
def daemon_stop():
    """Stop the running ATLAS daemon."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))

    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return

    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "shutdown"))
    if result.get("status") == "ok":
        click.echo("[daemon] Shutdown signal sent.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


@daemon.command("status")
def daemon_status():
    """Check if the ATLAS daemon is running."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))

    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return

    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "status"))
    if result.get("status") == "ok":
        payload = result.get("payload", {})
        click.echo(
            f"[daemon] Running. PID={payload.get('pid')} uptime={payload.get('uptime_seconds')}s"
        )
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


async def _send_daemon_command(socket_path: str, command: str) -> dict:
    client = DaemonSocketClient(socket_path)
    return await client.send(DaemonCommand(command=command))


async def _send_daemon_command_with_payload(
    socket_path: str, command: str, payload: dict
) -> dict:
    client = DaemonSocketClient(socket_path)
    return await client.send(DaemonCommand(command=command, payload=payload))


@daemon.command("pause")
def daemon_pause():
    """Pause the running daemon (stops accepting new tasks)."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "pause"))
    if result.get("status") == "ok":
        click.echo("[daemon] Paused.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


@daemon.command("resume")
def daemon_resume():
    """Resume a paused daemon."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(_send_daemon_command(socket_path, "resume"))
    if result.get("status") == "ok":
        click.echo("[daemon] Resumed.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


@daemon.command("kill")
@click.argument("task_id")
def daemon_kill(task_id: str):
    """Kill a specific running task."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if not pid_file.is_running():
        click.echo("[daemon] Not running.")
        return
    socket_path = str(Path(config.daemon.socket_path).expanduser())
    result = asyncio.run(
        _send_daemon_command_with_payload(socket_path, "kill", {"task_id": task_id})
    )
    if result.get("status") == "ok":
        killed = result.get("payload", {}).get("killed", False)
        if killed:
            click.echo(f"[daemon] Task {task_id} cancelled.")
        else:
            click.echo(f"[daemon] Task {task_id} not found or not active.")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


# --- Watch commands ---


@main.group()
def watch():
    """Manage filesystem watches."""
    pass


@watch.command("add")
@click.argument("pattern")
def watch_add(pattern: str):
    """Add a filesystem watch pattern."""
    click.echo(f"[watch] Added watch for: {pattern}")
    click.echo("[watch] Note: watch persistence requires daemon mode.")


@watch.command("list")
def watch_list():
    """List active filesystem watches."""
    config = _load_config()
    if not config.observation.watches:
        click.echo("[watch] No watches configured.")
        return
    for w in config.observation.watches:
        click.echo(f"  - {w}")


@main.command()
def status():
    """Show ATLAS status."""
    config = _load_config()
    pid_file = PidFile(str(Path(config.daemon.pid_file).expanduser()))
    if pid_file.is_running():
        click.echo(f"[status] Daemon running (PID {pid_file.read()})")
    else:
        click.echo(
            "[status] ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks."
        )


# --- Vault commands ---


@main.group()
def vault():
    """Manage the credential vault."""
    pass


@vault.command("set")
@click.argument("service")
@click.argument("key")
@click.option(
    "--value", prompt=True, hide_input=True, help="Credential value (prompted securely)"
)
@click.option("--passphrase", prompt=True, hide_input=True, help="Vault passphrase")
def vault_set(service: str, key: str, value: str, passphrase: str):
    """Store a credential in the vault."""
    asyncio.run(_vault_set(service, key, value, passphrase))


async def _vault_set(service: str, key: str, value: str, passphrase: str):
    from atlas.integrations.vault import CredentialVault

    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        v = await CredentialVault.create(db=db, passphrase=passphrase)
        await v.store(service, key, value)
        click.echo(f"[vault] Stored: {service}/{key}")
    finally:
        await db.close()


@vault.command("list")
def vault_list():
    """List stored credentials (services and keys only)."""
    asyncio.run(_vault_list())


async def _vault_list():
    data_dir = _ensure_data_dir()
    db_path = data_dir / "data" / "atlas.db"
    if not db_path.exists():
        click.echo("[vault] No credentials stored.")
        return
    db = DatabaseStore(str(db_path))
    await db.initialize()
    try:
        cursor = await db.db.execute(
            "SELECT service, key FROM credentials ORDER BY service, key"
        )
        rows = await cursor.fetchall()
        if not rows:
            click.echo("[vault] No credentials stored.")
            return
        for service, key in rows:
            click.echo(f"  {service}/{key}")
    finally:
        await db.close()


@vault.command("delete")
@click.argument("service")
@click.argument("key")
def vault_delete(service: str, key: str):
    """Delete a credential from the vault."""
    asyncio.run(_vault_delete(service, key))


async def _vault_delete(service: str, key: str):
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        cursor = await db.db.execute(
            "SELECT 1 FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        row = await cursor.fetchone()
        if row is None:
            click.echo(f"[vault] Not found: {service}/{key}")
            return
        await db.db.execute(
            "DELETE FROM credentials WHERE service=? AND key=?",
            (service, key),
        )
        await db.db.commit()
        click.echo(f"[vault] Deleted: {service}/{key}")
    finally:
        await db.close()


# --- Rules commands ---


@main.group()
def rules():
    """Manage standing approval rules."""
    pass


@rules.command("list")
def rules_list():
    """List all standing approval rules."""
    asyncio.run(_rules_list())


async def _rules_list():
    from atlas.control.approval_rules import ApprovalRuleStore

    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        all_rules = await store.list_rules()
        if not all_rules:
            click.echo("[rules] No standing rules configured.")
            return
        for r in all_rules:
            expires = f" (expires {r.expires_at})" if r.expires_at else ""
            click.echo(
                f"  {r.rule_id[:8]}  {r.match_skill}  risk<={r.match_risk}  → {r.decision}{expires}"
            )
            if r.description:
                click.echo(f"           {r.description}")
    finally:
        await db.close()


@rules.command("add")
@click.option("--skill", default="*", help="Skill pattern (glob), e.g. 'file.*'")
@click.option(
    "--risk",
    default="*",
    type=click.Choice(["low", "medium", "high", "*"]),
    help="Maximum risk level to match",
)
@click.option("--decision", required=True, type=click.Choice(["allow", "deny"]))
@click.option("--description", default="", help="Human-readable description")
def rules_add(skill: str, risk: str, decision: str, description: str):
    """Add a standing approval rule."""
    asyncio.run(_rules_add(skill, risk, decision, description))


async def _rules_add(skill: str, risk: str, decision: str, description: str):
    from atlas.contracts.types import ApprovalRule
    from atlas.control.approval_rules import ApprovalRuleStore

    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        rule = ApprovalRule(
            match_skill=skill,
            match_risk=risk,
            decision=decision,
            description=description,
        )
        rule_id = await store.add_rule(rule)
        click.echo(
            f"[rules] Created rule {rule_id[:8]}: {skill} risk<={risk} → {decision}"
        )
    finally:
        await db.close()


@rules.command("remove")
@click.argument("rule_id")
def rules_remove(rule_id: str):
    """Remove a standing approval rule by ID (prefix match)."""
    asyncio.run(_rules_remove(rule_id))


async def _rules_remove(rule_id_prefix: str):
    from atlas.control.approval_rules import ApprovalRuleStore

    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        store = ApprovalRuleStore(db)
        all_rules = await store.list_rules()
        # Support prefix matching for convenience
        matches = [r for r in all_rules if r.rule_id.startswith(rule_id_prefix)]
        if not matches:
            click.echo(f"[rules] No rule matching '{rule_id_prefix}'")
            return
        for r in matches:
            await store.remove_rule(r.rule_id)
            click.echo(f"[rules] Removed rule {r.rule_id[:8]}")
    finally:
        await db.close()


# --- Trust commands ---


@main.group()
def trust():
    """Manage skill trust and autonomy recommendations."""
    pass


@trust.command("recommendations")
def trust_recommendations():
    """List pending trust recommendations."""
    asyncio.run(_trust_recommendations())


async def _trust_recommendations():
    from atlas.control.trust import TrustTracker

    data_dir = _ensure_data_dir()
    config = _load_config()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        tracker = TrustTracker(
            db=db,
            escalation_threshold=config.trust.escalation_threshold,
            demotion_failure_count=config.trust.demotion_failure_count,
            demotion_window_size=config.trust.demotion_window_size,
        )
        recs = await tracker.list_recommendations(status="pending")
        if not recs:
            click.echo("[trust] No pending recommendations.")
            return
        for r in recs:
            click.echo(
                f"  {r.recommendation_id[:8]}  {r.skill_id}  {r.direction} → {r.recommended_level}"
            )
            click.echo(f"           evidence: {r.evidence}")
    finally:
        await db.close()


@trust.command("accept")
@click.argument("recommendation_id")
def trust_accept(recommendation_id: str):
    """Accept a trust recommendation (prefix match)."""
    asyncio.run(_trust_resolve(recommendation_id, accepted=True))


@trust.command("dismiss")
@click.argument("recommendation_id")
def trust_dismiss(recommendation_id: str):
    """Dismiss a trust recommendation (prefix match)."""
    asyncio.run(_trust_resolve(recommendation_id, accepted=False))


async def _trust_resolve(rec_id_prefix: str, accepted: bool):
    from atlas.control.trust import TrustTracker

    data_dir = _ensure_data_dir()
    config = _load_config()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        tracker = TrustTracker(
            db=db,
            escalation_threshold=config.trust.escalation_threshold,
            demotion_failure_count=config.trust.demotion_failure_count,
            demotion_window_size=config.trust.demotion_window_size,
        )
        recs = await tracker.list_recommendations(status="pending")
        matches = [r for r in recs if r.recommendation_id.startswith(rec_id_prefix)]
        if not matches:
            click.echo(f"[trust] No pending recommendation matching '{rec_id_prefix}'")
            return
        for r in matches:
            await tracker.resolve_recommendation(r.recommendation_id, accepted=accepted)
            action = "Accepted" if accepted else "Dismissed"
            click.echo(
                f"[trust] {action}: {r.skill_id} {r.direction} → {r.recommended_level}"
            )
    finally:
        await db.close()


@trust.command("status")
def trust_status():
    """Show trust records for all tracked skills."""
    asyncio.run(_trust_status())


async def _trust_status():
    data_dir = _ensure_data_dir()
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()
    try:
        cursor = await db.db.execute(
            "SELECT skill_id, successes, failures, total_invocations, "
            "autonomy_override, consecutive_successes "
            "FROM trust_records ORDER BY skill_id"
        )
        rows = await cursor.fetchall()
        if not rows:
            click.echo("[trust] No trust records.")
            return
        for r in rows:
            override = (
                f" (override: {AutonomyLevel(int(r[4])).name})"
                if r[4] is not None
                else ""
            )
            rate = round(r[1] / r[3] * 100, 1) if r[3] > 0 else 0
            click.echo(
                f"  {r[0]}  {r[1]}ok {r[2]}fail ({rate}% success, {r[3]} total){override}"
            )
    finally:
        await db.close()


if __name__ == "__main__":
    main()
