"""tmux_agent — Launch Claude Code sessions in background tmux windows.

One-liner background agent spawning with optional Agent Teams support.

Usage:
    from scripts.tmux_agent import launch, is_alive, kill_session

    session = launch(
        "my-worker",
        system_prompt="You are a code reviewer.",
        initial_message="Review ~/dev/app/src/auth.py",
        cwd="~/dev/app",
    )
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
PROMPT_DIR = VAULT_DIR / "storage" / "agent-prompts"


@dataclass(frozen=True)
class AgentSession:
    """Immutable snapshot of a launched agent session."""

    session_name: str
    session_id: str  # 8-char hex
    prompt_file: str  # path to system prompt file
    cwd: str
    started_at: float  # unix timestamp


# ── Public API ──────────────────────────────────────────────


def launch(
    session_name: str,
    *,
    system_prompt: str = "",
    initial_message: str = "",
    cwd: str | None = None,
    env_vars: dict[str, str] | None = None,
    agent_teams: bool = False,
    claude_path: str | None = None,
    on_done_hook: str | None = None,
) -> AgentSession:
    """Spawn a Claude Code session in a new tmux session.

    Args:
        session_name: tmux session name (must be unique).
        system_prompt: Text appended as system prompt via --append-system-prompt.
        initial_message: First message sent to Claude after launch.
        cwd: Working directory for the session. Defaults to current dir.
        env_vars: Extra environment variables injected into the session.
        agent_teams: If True, sets CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true.
        claude_path: Explicit path to the claude binary. Auto-detected if None.
        on_done_hook: Shell command chained after Claude exits (` ; <hook> || true`).

    Returns:
        AgentSession with session metadata.

    Raises:
        FileNotFoundError: If claude binary is not found.
        RuntimeError: If tmux session creation fails.
    """
    session_id = uuid.uuid4().hex[:8]
    resolved_claude = claude_path or _find_claude()
    work_dir = cwd or str(Path.cwd())

    # 1. Write prompt file
    prompt_file = _write_prompt_file(session_id, system_prompt)

    # 2. Build command
    cmd = _build_cmd(
        claude_path=resolved_claude,
        prompt_file=str(prompt_file),
        initial_message=initial_message,
        env_vars=env_vars,
        agent_teams=agent_teams,
        on_done_hook=on_done_hook,
    )

    # 3. Create tmux session
    escaped = cmd.replace("'", "'\\''")
    tmux_cmd = [
        "tmux", "new-session", "-d",
        "-s", session_name,
        "-c", work_dir,
        "-e", f"CC_SESSION={session_name}",
        escaped,
    ]
    result = subprocess.run(tmux_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"tmux session creation failed: {result.stderr.strip()}"
        )

    return AgentSession(
        session_name=session_name,
        session_id=session_id,
        prompt_file=str(prompt_file),
        cwd=work_dir,
        started_at=time.time(),
    )


def is_alive(session_name: str) -> bool:
    """Check if a tmux session exists and is running."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )
    return result.returncode == 0


def list_sessions(prefix: str = "") -> list[str]:
    """List tmux session names, optionally filtered by prefix."""
    result = subprocess.run(
        ["tmux", "ls", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    names = result.stdout.strip().splitlines()
    if prefix:
        names = [n for n in names if n.startswith(prefix)]
    return sorted(names)


def send_message(session_name: str, text: str) -> bool:
    """Send text input to a running tmux session.

    For long messages (>500 chars), uses tmux load-buffer to avoid
    shell escaping issues.

    Returns:
        True if send succeeded, False otherwise.
    """
    if not is_alive(session_name):
        return False

    if len(text) > 500:
        return _send_via_buffer(session_name, text)

    result = subprocess.run(
        ["tmux", "send-keys", "-t", session_name, text, "Enter"],
        capture_output=True,
    )
    return result.returncode == 0


def kill_session(session_name: str) -> bool:
    """Gracefully stop a Claude session, then force-kill if needed.

    Sends /exit first, waits 3 seconds, then kills the tmux session.

    Returns:
        True if session was terminated, False if it didn't exist.
    """
    if not is_alive(session_name):
        return False

    # Graceful exit
    subprocess.run(
        ["tmux", "send-keys", "-t", session_name, "/exit", "Enter"],
        capture_output=True,
    )
    time.sleep(3)

    # Force kill if still alive
    if is_alive(session_name):
        subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
        )
    return True


# ── Internal Helpers ────────────────────────────────────────


def _find_claude() -> str:
    """Locate the claude CLI binary.

    Raises:
        FileNotFoundError: If claude is not on PATH.
    """
    path = shutil.which("claude")
    if path is None:
        raise FileNotFoundError(
            "claude CLI not found on PATH. "
            "Install from https://docs.anthropic.com/claude-code"
        )
    return path


def _write_prompt_file(session_id: str, content: str) -> Path:
    """Write system prompt to a file under storage/agent-prompts/.

    Returns:
        Path to the created prompt file.
    """
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    prompt_file = PROMPT_DIR / f"{session_id}.md"
    prompt_file.write_text(content, encoding="utf-8")
    return prompt_file


def _build_cmd(
    *,
    claude_path: str,
    prompt_file: str,
    initial_message: str = "",
    env_vars: dict[str, str] | None = None,
    agent_teams: bool = False,
    on_done_hook: str | None = None,
) -> str:
    """Assemble the shell command string for tmux."""
    # Environment prefix
    all_env: dict[str, str] = dict(env_vars or {})
    if agent_teams:
        all_env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "true"

    env_prefix = ""
    if all_env:
        parts = [f"{k}={shlex.quote(v)}" for k, v in sorted(all_env.items())]
        env_prefix = " ".join(parts) + " "

    # Core command
    cmd = f"{env_prefix}{claude_path} --dangerously-skip-permissions"

    # System prompt
    cmd += f' --append-system-prompt "$(cat {shlex.quote(prompt_file)})"'

    # Initial message
    if initial_message:
        cmd += f" {shlex.quote(initial_message)}"

    # Done hook
    if on_done_hook:
        cmd += f" ; {on_done_hook} || true"

    return cmd


def _send_via_buffer(session_name: str, text: str) -> bool:
    """Send long text via tmux load-buffer to avoid escaping issues."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", prefix="tmux-agent-", suffix=".txt", delete=False
    )
    try:
        tmp.write(text)
        tmp.close()
        load = subprocess.run(
            ["tmux", "load-buffer", tmp.name], capture_output=True
        )
        if load.returncode != 0:
            return False
        paste = subprocess.run(
            ["tmux", "paste-buffer", "-t", session_name], capture_output=True
        )
        if paste.returncode != 0:
            return False
        enter = subprocess.run(
            ["tmux", "send-keys", "-t", session_name, "Enter"],
            capture_output=True,
        )
        return enter.returncode == 0
    finally:
        os.unlink(tmp.name)
