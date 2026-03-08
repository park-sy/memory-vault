"""Tests for tmux_agent module.

Unit tests mock subprocess/shutil to avoid actual tmux/claude dependencies.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.tmux_agent import (
    AgentSession,
    _build_cmd,
    _find_claude,
    _write_prompt_file,
    is_alive,
    kill_session,
    launch,
    list_sessions,
    send_message,
    PROMPT_DIR,
)


class TestFindClaude(unittest.TestCase):
    """_find_claude: locate claude binary on PATH."""

    @patch("scripts.tmux_agent.shutil.which", return_value="/usr/local/bin/claude")
    def test_found(self, mock_which):
        assert _find_claude() == "/usr/local/bin/claude"
        mock_which.assert_called_once_with("claude")

    @patch("scripts.tmux_agent.shutil.which", return_value=None)
    def test_not_found_raises(self, mock_which):
        with self.assertRaises(FileNotFoundError):
            _find_claude()


class TestWritePromptFile(unittest.TestCase):
    """_write_prompt_file: create prompt file under storage/agent-prompts/."""

    def test_creates_file_with_content(self):
        content = "You are a code reviewer."
        result = _write_prompt_file("test1234", content)

        self.assertEqual(result, PROMPT_DIR / "test1234.md")
        self.assertTrue(result.exists())
        self.assertEqual(result.read_text(encoding="utf-8"), content)

        # Cleanup
        result.unlink(missing_ok=True)

    def test_empty_content(self):
        result = _write_prompt_file("empty000", "")
        self.assertEqual(result.read_text(encoding="utf-8"), "")
        result.unlink(missing_ok=True)


class TestBuildCmd(unittest.TestCase):
    """_build_cmd: assemble shell command string."""

    def test_basic(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
        )
        self.assertIn("/usr/bin/claude", cmd)
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--append-system-prompt", cmd)
        self.assertIn("/tmp/prompt.md", cmd)
        # No env prefix
        self.assertTrue(cmd.startswith("/usr/bin/claude"))

    def test_agent_teams_env(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
            agent_teams=True,
        )
        self.assertIn("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true", cmd)

    def test_custom_env_vars(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
            env_vars={"MY_VAR": "hello"},
        )
        self.assertIn("MY_VAR=hello", cmd)

    def test_initial_message(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
            initial_message="Review auth.py",
        )
        # Message should be shell-quoted at the end
        self.assertIn("Review auth.py", cmd)

    def test_on_done_hook(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
            on_done_hook="python3 scripts/notify.py 'done'",
        )
        self.assertIn(" ; python3 scripts/notify.py 'done' || true", cmd)

    def test_combined(self):
        cmd = _build_cmd(
            claude_path="/usr/bin/claude",
            prompt_file="/tmp/prompt.md",
            initial_message="hello",
            env_vars={"FOO": "bar"},
            agent_teams=True,
            on_done_hook="echo done",
        )
        # Env vars sorted alphabetically
        self.assertIn("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true", cmd)
        self.assertIn("FOO=bar", cmd)
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("hello", cmd)
        self.assertIn(" ; echo done || true", cmd)


class TestIsAlive(unittest.TestCase):
    """is_alive: check tmux session existence."""

    @patch("scripts.tmux_agent.subprocess.run")
    def test_alive(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(is_alive("my-session"))
        mock_run.assert_called_once_with(
            ["tmux", "has-session", "-t", "my-session"],
            capture_output=True,
        )

    @patch("scripts.tmux_agent.subprocess.run")
    def test_not_alive(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(is_alive("nonexistent"))


class TestListSessions(unittest.TestCase):
    """list_sessions: parse tmux ls output."""

    @patch("scripts.tmux_agent.subprocess.run")
    def test_with_prefix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="cc-pool-1\ncc-pool-2\ncc-factory\nother-session\n",
        )
        result = list_sessions(prefix="cc-pool")
        self.assertEqual(result, ["cc-pool-1", "cc-pool-2"])

    @patch("scripts.tmux_agent.subprocess.run")
    def test_no_prefix(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="a\nb\nc\n",
        )
        result = list_sessions()
        self.assertEqual(result, ["a", "b", "c"])

    @patch("scripts.tmux_agent.subprocess.run")
    def test_tmux_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = list_sessions()
        self.assertEqual(result, [])


class TestSendMessage(unittest.TestCase):
    """send_message: deliver text to tmux session."""

    @patch("scripts.tmux_agent.subprocess.run")
    @patch("scripts.tmux_agent.is_alive", return_value=True)
    def test_short_message(self, mock_alive, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = send_message("my-session", "hello")
        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "my-session", "hello", "Enter"],
            capture_output=True,
        )

    @patch("scripts.tmux_agent.is_alive", return_value=False)
    def test_dead_session(self, mock_alive):
        result = send_message("dead-session", "hello")
        self.assertFalse(result)


class TestKillSession(unittest.TestCase):
    """kill_session: graceful then force kill."""

    @patch("scripts.tmux_agent.time.sleep")
    @patch("scripts.tmux_agent.subprocess.run")
    @patch("scripts.tmux_agent.is_alive")
    def test_graceful_exit(self, mock_alive, mock_run, mock_sleep):
        # First call: alive (for initial check)
        # Second call: dead after /exit
        mock_alive.side_effect = [True, False]
        mock_run.return_value = MagicMock(returncode=0)

        result = kill_session("my-session")
        self.assertTrue(result)
        # Should have sent /exit
        mock_run.assert_called_once_with(
            ["tmux", "send-keys", "-t", "my-session", "/exit", "Enter"],
            capture_output=True,
        )

    @patch("scripts.tmux_agent.time.sleep")
    @patch("scripts.tmux_agent.subprocess.run")
    @patch("scripts.tmux_agent.is_alive")
    def test_force_kill(self, mock_alive, mock_run, mock_sleep):
        # Stays alive after /exit → force kill needed
        mock_alive.side_effect = [True, True]
        mock_run.return_value = MagicMock(returncode=0)

        result = kill_session("my-session")
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)  # /exit + kill-session

    @patch("scripts.tmux_agent.is_alive", return_value=False)
    def test_nonexistent(self, mock_alive):
        result = kill_session("no-such-session")
        self.assertFalse(result)


class TestLaunch(unittest.TestCase):
    """launch: full integration of prompt file + cmd build + tmux create."""

    @patch("scripts.tmux_agent.subprocess.run")
    @patch("scripts.tmux_agent._find_claude", return_value="/usr/bin/claude")
    def test_basic_launch(self, mock_find, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        session = launch(
            "test-worker",
            system_prompt="You are helpful.",
            cwd="/tmp/project",
        )

        self.assertIsInstance(session, AgentSession)
        self.assertEqual(session.session_name, "test-worker")
        self.assertEqual(len(session.session_id), 8)
        self.assertEqual(session.cwd, "/tmp/project")
        self.assertTrue(session.prompt_file.endswith(".md"))
        self.assertGreater(session.started_at, 0)

        # Verify tmux was called
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[0], "tmux")
        self.assertEqual(call_args[1], "new-session")
        self.assertIn("-s", call_args)
        self.assertIn("test-worker", call_args)

        # Cleanup prompt file
        Path(session.prompt_file).unlink(missing_ok=True)

    @patch("scripts.tmux_agent.subprocess.run")
    @patch("scripts.tmux_agent._find_claude", return_value="/usr/bin/claude")
    def test_launch_failure_raises(self, mock_find, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="duplicate session: test-worker"
        )

        with self.assertRaises(RuntimeError) as ctx:
            launch("test-worker")

        self.assertIn("duplicate session", str(ctx.exception))

        # Cleanup any prompt file created
        for f in PROMPT_DIR.glob("*.md"):
            if f.stat().st_size == 0:
                f.unlink(missing_ok=True)


class TestAgentSessionImmutability(unittest.TestCase):
    """AgentSession is frozen dataclass."""

    def test_frozen(self):
        session = AgentSession("s", "id", "/tmp/p.md", "/tmp", 1.0)
        with self.assertRaises(AttributeError):
            session.session_name = "other"


if __name__ == "__main__":
    unittest.main()
