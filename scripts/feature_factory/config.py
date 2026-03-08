"""Feature Factory configuration — constants, paths, intervals."""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

VAULT_DIR = Path(__file__).parent.parent.parent
SCRIPTS_DIR = VAULT_DIR / "scripts"
STORAGE_DIR = VAULT_DIR / "storage"
FACTORY_DB_PATH = str(STORAGE_DIR / "feature-factory.db")

POOL_SH = str(SCRIPTS_DIR / "pool.sh")
NOTIFY_PY = str(SCRIPTS_DIR / "notify.py")
CHECK_INBOX_PY = str(SCRIPTS_DIR / "check_inbox.py")

# whos-life CLI
WHOS_LIFE_DIR = Path.home() / "dev" / "whos-life"
WHOS_LIFE_CLI = str(WHOS_LIFE_DIR / "cli.py")
WHOS_LIFE_PYTHON = str(WHOS_LIFE_DIR / ".venv" / "bin" / "python")

# ── Daemon Identity ──────────────────────────────────────────────────────────

DAEMON_ID = "cc-factory"

# ── Intervals (seconds) ─────────────────────────────────────────────────────

TICK_INTERVAL = 3           # main loop sleep
HOUSEKEEP_INTERVAL = 60     # idle worker cleanup cycle
APPROVAL_TIMEOUT = 1800     # 30 min — remind user if no response
STALL_TIMEOUT = 900         # 15 min — worker stall detection

# ── Worker Pool ──────────────────────────────────────────────────────────────

BASE_POOL_SIZE = 1          # always-alive minimum workers
MAX_POOL_SIZE = 3           # hard cap (token_gate applies dynamic limit on top)
IDLE_TIMEOUT = 600          # 10 min — reclaim excess idle workers
DEFAULT_PROJECT_DIR = str(WHOS_LIFE_DIR)

# ── Pipeline Stages ──────────────────────────────────────────────────────────

STAGES = (
    "idea", "spec", "queued", "designing",
    "testing", "stable", "coding", "done",
)

# Approval gates: stage transitions requiring user confirmation
APPROVAL_GATES = {
    "spec_to_queued":   {"from": "spec",    "cli_cmd": "approve-to-queue"},
    "design_plan":      {"from": "designing", "cli_cmd": "approve-plan"},
    "testing_to_stable": {"from": "testing", "cli_cmd": "approve-stable"},
    "coding_plan":      {"from": "coding",  "cli_cmd": "approve-plan"},
}

# Stage → worker role mapping
STAGE_ROLES = {
    "idea":      "coder",      # domain analysis
    "spec":      "planner",    # spec authoring
    "designing": "planner",    # SKILL.md creation
    "testing":   "qa",         # command-level verification
    "coding":    "coder",      # implementation
}

# ── Concurrency ─────────────────────────────────────────────────────────────

MAX_CONCURRENT_FEATURES = 3   # max features running pipeline simultaneously
STAGE_CONCURRENCY = {
    "designing": 1,           # only 1 feature in designing at a time
    "coding": 1,              # only 1 feature in coding at a time
    "testing": 1,             # only 1 feature in testing at a time
    "spec": 2,                # 2 features can be spec'd in parallel
    "idea": 2,                # 2 ideas can be analyzed in parallel
}

# ── Supervision Mode ─────────────────────────────────────────────────────────

DEFAULT_SUPERVISION = "on"  # "on" or "off"

# ── Notification Channels ────────────────────────────────────────────────────

CHANNEL_APPROVAL = "approval"
CHANNEL_OPS = "ops"
CHANNEL_REPORT = "report"


# ── Runtime Config Reader ───────────────────────────────────────────────────

def get_runtime_int(key: str, default: int) -> int:
    """factory_config DB에서 읽기. 실패 시 default 반환."""
    from . import db
    val = db.get_config(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default
