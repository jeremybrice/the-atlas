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
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import (
    Mission, parse_task_plan, PLANNING_PROMPT_TEMPLATE, PLANNING_SYSTEM_PROMPT,
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
@click.option("--autonomy", type=click.Choice(["observe", "suggest", "act"]), default="act",
              help="Autonomy level")
@click.option("--auto-approve", is_flag=True, help="Auto-approve all actions (for testing)")
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
    return await client.send(DaemonCommand(command="goal", payload={"goal_text": goal_text}))


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
    approval = ApprovalWorkflow(auto_approve=auto_approve)

    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    # Initialize vector search components if enabled
    context_assembler = ContextAssembler()

    if config.memory.vector_search.enabled:
        try:
            from atlas.memory.embeddings import EmbeddingProvider
            from atlas.memory.migration import VectorMigration
            from atlas.memory.vector_store import VectorStore

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise ValueError("VOYAGE_API_KEY environment variable not set")

            embedding_provider = EmbeddingProvider(
                api_key=api_key, model=config.memory.vector_search.model,
            )
            vector_store = VectorStore(db, model=config.memory.vector_search.model)

            # Update episodic store with embedding components
            episodic = EpisodicMemoryStore(
                db, embedding_provider=embedding_provider, vector_store=vector_store,
            )

            # Run migration if needed
            migration = VectorMigration(db, episodic, vector_store, embedding_provider)
            if not await migration.is_complete():
                click.echo("[vector-search] Migrating existing episodes...")
                count = await migration.run()
                if count:
                    click.echo(f"[vector-search] Embedded {count} episodes")

            click.echo("[vector-search] Semantic search enabled")
        except Exception as e:
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
        for config_file in ["pyproject.toml", "setup.py", "setup.cfg",
                            "requirements.txt", "package.json", "Makefile"]:
            try:
                content = fs.read(config_file)
                context_parts.append(f"{config_file}:\n{content}")
            except Exception:
                pass

        prompt = PLANNING_PROMPT_TEMPLATE.format(
            goal=goal_text, skills=skills_desc, context=" | ".join(context_parts)
        )

        try:
            response = await env.claude_oneshot(prompt, system_prompt=PLANNING_SYSTEM_PROMPT)
            tasks = parse_task_plan(response.content)
        except Exception as e:
            click.echo(f"[error] Planning failed: {e}", err=True)
            sys.exit(1)

        if not tasks:
            click.echo("[error] Could not parse a task plan from Claude's response.", err=True)
            click.echo(f"[debug] Raw response ({len(response.content)} chars):", err=True)
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
            click.echo(f"[complete] {completed}/{total} tasks succeeded. Episode recorded.")
        else:
            click.echo(f"[failed] {completed}/{total} tasks succeeded. Mission failed.", err=True)
            for t in result.tasks:
                if t.error:
                    click.echo(f"  - {t.description}: {t.error}", err=True)
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
    approval = ApprovalWorkflow(auto_approve=True)  # daemon mode auto-approves
    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    # Initialize vector search components if enabled
    context_assembler = ContextAssembler()

    if config.memory.vector_search.enabled:
        try:
            from atlas.memory.embeddings import EmbeddingProvider as DaemonEmbeddingProvider
            from atlas.memory.migration import VectorMigration as DaemonVectorMigration
            from atlas.memory.vector_store import VectorStore as DaemonVectorStore

            api_key = os.environ.get("VOYAGE_API_KEY")
            if not api_key:
                raise ValueError("VOYAGE_API_KEY environment variable not set")

            embedding_provider = DaemonEmbeddingProvider(
                api_key=api_key, model=config.memory.vector_search.model,
            )
            vector_store = DaemonVectorStore(db, model=config.memory.vector_search.model)

            episodic = EpisodicMemoryStore(
                db, embedding_provider=embedding_provider, vector_store=vector_store,
            )

            migration = DaemonVectorMigration(db, episodic, vector_store, embedding_provider)
            if not await migration.is_complete():
                click.echo("[vector-search] Migrating existing episodes...")
                await migration.run()

            click.echo("[vector-search] Semantic search enabled (daemon)")
        except Exception as e:
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
    )

    async def goal_executor(goal_text: str) -> dict:
        tasks = parse_task_plan(
            (await env.claude_oneshot(
                PLANNING_PROMPT_TEMPLATE.format(
                    goal=goal_text,
                    skills=", ".join(s.skill_id for s in registry.list_all()),
                    context="daemon mode",
                ),
                system_prompt=PLANNING_SYSTEM_PROMPT,
            )).content
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
            router.add_rule(ReactiveRule(
                name=rule_cfg.get("name", "unnamed"),
                event_type=EventType(rule_cfg.get("trigger", {}).get("type", "filesystem")),
                source_pattern=rule_cfg.get("trigger", {}).get("pattern", "*"),
                goal_template=rule_cfg.get("goal", ""),
                cooldown_seconds=rule_cfg.get("cooldown", config.reactive.cooldown_default_seconds),
            ))

    obs_engine = ObservationEngine(router=router, goal_handler=goal_executor)
    for watch_path in config.observation.watches:
        obs_engine.add_filesystem_watch(
            watch_path, ["*"], debounce_seconds=config.observation.filesystem_debounce_seconds,
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
            )
            dashboard_app = dashboard_server.create_app()
            for resource in dashboard_app.router.resources():
                for route in resource:
                    http_app.router.add_route(route.method, resource.canonical, route.handler)

    daemon_loop = DaemonLoop(
        socket_path=socket_path,
        pid_path=pid_path,
        goal_executor=goal_executor,
        mcp_bridge=mcp_bridge,
        mcp_servers=config.mcp.servers,
        http_app=http_app,
        http_host=config.webhook.host,
        http_port=config.webhook.port,
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
        click.echo(f"[daemon] Running. PID={payload.get('pid')} uptime={payload.get('uptime_seconds')}s")
    else:
        click.echo(f"[daemon] Error: {result.get('error', 'unknown')}", err=True)


async def _send_daemon_command(socket_path: str, command: str) -> dict:
    client = DaemonSocketClient(socket_path)
    return await client.send(DaemonCommand(command=command))


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
        click.echo("[status] ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks.")


# --- Vault commands ---

@main.group()
def vault():
    """Manage the credential vault."""
    pass


@vault.command("set")
@click.argument("service")
@click.argument("key")
@click.option("--value", prompt=True, hide_input=True, help="Credential value (prompted securely)")
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


if __name__ == "__main__":
    main()
