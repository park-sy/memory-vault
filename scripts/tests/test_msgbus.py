"""test_msgbus.py — MsgBus core tests (~27 assertions)."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from msgbus import MsgBusConfig, init_db, send, receive, peek, ack, get_message, \
    link_channel, find_by_channel_msg, cleanup_expired, cleanup_old, count_pending, status
from tests.harness import Suite, run_suite, TestResult
from typing import List


def _make_config() -> MsgBusConfig:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return MsgBusConfig(db_path=f.name)


def _test_msgbus(s: Suite) -> None:
    # 1. init_db idempotent
    cfg = _make_config()
    init_db(cfg)
    init_db(cfg)  # 2nd call should not error
    s.check("init_db idempotent (2 calls no error)", True)

    # 2. send returns int id
    cfg = _make_config()
    init_db(cfg)
    msg_id = send(cfg, "a", "b", "notify", {"text": "hello"})
    s.check_is_instance("send returns int id", msg_id, int)
    s.check_gt("send id >= 1", msg_id, 0)

    # 3. send invalid msg_type raises ValueError
    s.check_raises("send invalid msg_type raises ValueError", ValueError,
                   lambda: send(cfg, "a", "b", "bogus", "x"))

    # 4-5. send invalid priority
    s.check_raises("send priority=0 raises ValueError", ValueError,
                   lambda: send(cfg, "a", "b", "notify", "x", priority=0))
    s.check_raises("send priority=10 raises ValueError", ValueError,
                   lambda: send(cfg, "a", "b", "notify", "x", priority=10))

    # 6-8. payload serialization: dict, string, list
    cfg2 = _make_config()
    init_db(cfg2)

    id_dict = send(cfg2, "s", "r", "notify", {"key": "value"})
    msg = get_message(cfg2, id_dict)
    s.check_eq("send dict payload serialized", json.loads(msg.payload), {"key": "value"})

    id_str = send(cfg2, "s", "r", "notify", "plain text")
    msg2 = get_message(cfg2, id_str)
    s.check_eq("send string payload as-is", msg2.payload, "plain text")

    id_list = send(cfg2, "s", "r", "notify", [1, 2, 3])
    msg3 = get_message(cfg2, id_list)
    s.check_eq("send list payload serialized", json.loads(msg3.payload), [1, 2, 3])

    # 9. receive: pending messages returned
    cfg3 = _make_config()
    init_db(cfg3)
    send(cfg3, "a", "worker1", "task", "job1")
    send(cfg3, "a", "worker1", "task", "job2")
    msgs = receive(cfg3, "worker1")
    s.check_eq("receive returns 2 pending", len(msgs), 2)

    # 10. receive marks as read (peek after should be empty)
    peeked = peek(cfg3, "worker1")
    s.check_eq("peek after receive is empty", len(peeked), 0)

    # 11. receive limit respected
    cfg4 = _make_config()
    init_db(cfg4)
    for i in range(5):
        send(cfg4, "a", "worker2", "task", f"job{i}")
    msgs = receive(cfg4, "worker2", limit=2)
    s.check_eq("receive limit=2 returns 2", len(msgs), 2)

    # 12. receive priority ordering (lower priority number = higher urgency = first)
    cfg5 = _make_config()
    init_db(cfg5)
    send(cfg5, "a", "worker3", "task", "low-urgency", priority=9)
    send(cfg5, "a", "worker3", "task", "high-urgency", priority=1)
    msgs = receive(cfg5, "worker3")
    s.check_eq("receive priority ordering: P1 first", msgs[0].priority, 1)

    # 13. peek does not mark as read
    cfg6 = _make_config()
    init_db(cfg6)
    send(cfg6, "a", "worker4", "notify", "peek-test")
    peeked = peek(cfg6, "worker4")
    s.check_eq("peek returns 1", len(peeked), 1)
    still_pending = receive(cfg6, "worker4")
    s.check_eq("receive after peek still returns 1", len(still_pending), 1)

    # 14. ack marks as processed
    cfg7 = _make_config()
    init_db(cfg7)
    mid = send(cfg7, "a", "b", "notify", "ack-test")
    receive(cfg7, "b")  # mark as read first
    ack(cfg7, mid)
    msg = get_message(cfg7, mid)
    s.check_eq("ack sets status to processed", msg.status, "processed")

    # 15. ack nonexistent id raises ValueError
    s.check_raises("ack missing id raises ValueError", ValueError,
                   lambda: ack(cfg7, 99999))

    # 16-17. get_message: existing and None
    cfg8 = _make_config()
    init_db(cfg8)
    mid2 = send(cfg8, "a", "b", "notify", "get-test")
    s.check_not_none("get_message returns message", get_message(cfg8, mid2))
    s.check_none("get_message nonexistent returns None", get_message(cfg8, 99999))

    # 18-19. payload_dict: JSON and non-JSON
    cfg9 = _make_config()
    init_db(cfg9)
    mid_json = send(cfg9, "a", "b", "notify", {"k": "v"})
    msg_json = get_message(cfg9, mid_json)
    s.check_eq("payload_dict parses JSON", msg_json.payload_dict, {"k": "v"})

    mid_plain = send(cfg9, "a", "b", "notify", "not-json")
    msg_plain = get_message(cfg9, mid_plain)
    s.check_eq("payload_dict wraps non-JSON", msg_plain.payload_dict, {"raw": "not-json"})

    # 20-21. link_channel + find_by_channel_msg
    cfg10 = _make_config()
    init_db(cfg10)
    mid3 = send(cfg10, "a", "b", "notify", "link-test")
    link_channel(cfg10, mid3, "telegram", "tg_123")
    found = find_by_channel_msg(cfg10, "telegram", "tg_123")
    s.check_not_none("find_by_channel_msg returns message", found)
    s.check_eq("find_by_channel_msg correct id", found.id, mid3)

    not_found = find_by_channel_msg(cfg10, "telegram", "nonexistent")
    s.check_none("find_by_channel_msg not found returns None", not_found)

    # 22. reply_to threading
    cfg11 = _make_config()
    init_db(cfg11)
    parent_id = send(cfg11, "a", "b", "notify", "parent")
    child_id = send(cfg11, "b", "a", "result", "child", reply_to=parent_id)
    child_msg = get_message(cfg11, child_id)
    s.check_eq("reply_to links to parent", child_msg.reply_to, parent_id)

    # 23. count_pending
    cfg12 = _make_config()
    init_db(cfg12)
    send(cfg12, "a", "counter-target", "notify", "1")
    send(cfg12, "a", "counter-target", "notify", "2")
    send(cfg12, "a", "other", "notify", "3")
    s.check_eq("count_pending for target", count_pending(cfg12, "counter-target"), 2)

    # 24. cleanup_expired
    cfg13 = _make_config()
    init_db(cfg13)
    send(cfg13, "a", "b", "notify", "expired", expires_at="2020-01-01 00:00:00")
    expired_count = cleanup_expired(cfg13)
    s.check_gt("cleanup_expired finds 1", expired_count, 0)

    # 25-26. cleanup_old: deletes processed + nullifies reply_to FK
    cfg14 = _make_config()
    init_db(cfg14)
    old_id = send(cfg14, "a", "b", "notify", "old-msg")
    ack(cfg14, old_id)
    # Manually backdate for test
    import sqlite3
    conn = sqlite3.connect(cfg14.db_path)
    conn.execute("UPDATE messages SET created_at = '2020-01-01 00:00:00' WHERE id = ?", (old_id,))
    conn.commit()
    conn.close()

    reply_id = send(cfg14, "b", "a", "result", "reply", reply_to=old_id)
    deleted = cleanup_old(cfg14, days=1)
    s.check_gt("cleanup_old deleted old messages", deleted, 0)
    reply_msg = get_message(cfg14, reply_id)
    s.check_none("cleanup_old nullified reply_to", reply_msg.reply_to)

    # 27. status aggregate
    cfg15 = _make_config()
    init_db(cfg15)
    send(cfg15, "a", "b", "notify", "s1")
    send(cfg15, "a", "c", "notify", "s2")
    stats = status(cfg15)
    s.check_eq("status total", stats["total"], 2)
    s.check("status has pending_by_recipient", "pending_by_recipient" in stats)


def run(verbose: bool = False) -> List[TestResult]:
    return run_suite("msgbus", _test_msgbus)
