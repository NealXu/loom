"""Tests for the inbox file watcher (Task 23)."""

import json
import tempfile
import os
import time
from pathlib import Path

import pytest

from loom.core.store import Store
from loom.triggers.inbox import InboxWatcher


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "test.db"
    with Store(str(db)) as s:
        yield s


@pytest.fixture
def inbox_dir(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    return str(d)


def test_inbox_watcher_creation(store, inbox_dir):
    """InboxWatcher initialises without error given a Store and directory."""
    watcher = InboxWatcher(store, inbox_dir)
    assert watcher.store is store
    assert watcher.inbox_dir == inbox_dir


def test_process_file_creates_event(store, inbox_dir):
    """_process_file reads a file and inserts an event with source='inbox'."""
    # Create a test file inside the inbox directory
    file_path = os.path.join(inbox_dir, "task.yaml")
    with open(file_path, "w") as f:
        f.write("title: Do something\n")

    watcher = InboxWatcher(store, inbox_dir)
    watcher._process_file(file_path)

    row = store.conn.execute(
        "SELECT source, payload FROM events WHERE source = 'inbox'"
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload"])
    assert payload["file"] == file_path
    assert "content" in payload
    assert "Do something" in payload["content"]


def test_start_and_stop_observer(store, inbox_dir):
    """start() launches the watchdog observer; stop() shuts it down."""
    from watchdog.observers import Observer

    watcher = InboxWatcher(store, inbox_dir)
    watcher.start()
    assert watcher.observer is not None
    assert watcher.observer.is_alive()

    watcher.stop()
    # After stop(), the observer thread should no longer be alive
    assert not watcher.observer.is_alive()


def test_process_file_handles_errors(store, inbox_dir):
    """_process_file does not crash when an exception occurs (e.g. file not found)."""
    watcher = InboxWatcher(store, inbox_dir)
    non_existent = os.path.join(inbox_dir, "does_not_exist.yaml")
    # Should not raise — the error is caught and logged internally
    watcher._process_file(non_existent)
