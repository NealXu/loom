"""Inbox file watcher — monitors a directory for new files and records events."""

import json
import logging
from datetime import datetime

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from loom.core.models import Event


class _InboxHandler(FileSystemEventHandler):
    """Watchdog handler that delegates to InboxWatcher._process_file."""

    def __init__(self, watcher):
        self._watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self._watcher._process_file(event.src_path)


class InboxWatcher:
    """Watch *inbox_dir* for new files and record each as an event."""

    def __init__(self, store, inbox_dir: str, observer=None):
        self.store = store
        self.inbox_dir = inbox_dir
        self.observer = observer  # injectable for testing

    def start(self):
        """Start watching the inbox directory."""
        if self.observer is None:
            self.observer = Observer()
        handler = _InboxHandler(self)
        self.observer.schedule(handler, self.inbox_dir, recursive=False)
        self.observer.start()

    def stop(self):
        """Stop watching."""
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()

    def _process_file(self, file_path: str):
        """Read a file and insert an event with source='inbox'."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            event = Event(
                source="inbox",
                payload={"file": file_path, "content": content},
            )
            self.store.conn.execute(
                """INSERT INTO events (source, payload, received_at, consumed_by_instance)
                   VALUES (?, ?, ?, ?)""",
                (event.source, json.dumps(event.payload),
                 event.received_at.isoformat(), event.consumed_by_instance),
            )
            self.store.conn.commit()
        except Exception:
            logging.exception("Failed to process inbox file: %s", file_path)
