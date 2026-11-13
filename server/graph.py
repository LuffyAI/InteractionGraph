"""Persistent event-backed conversation DAG. No third-party dependencies."""
import json
import sqlite3
import threading
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def node_id(*parts):
    return str(uuid5(NAMESPACE_URL, json.dumps(parts)))


class Graph:
    def __init__(self, database):
        self.condition = threading.Condition(threading.RLock())
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.turns = {}
        self.sessions = {}
        self.nodes = {}
        self.revision = 0
        for payload, in self.db.execute('SELECT payload FROM events ORDER BY rowid'):
            self._apply(json.loads(payload))

    def close(self):
        self.db.close()

    def ingest(self, record):
        with self.condition:
            with self.db:
                cursor = self.db.execute('INSERT OR IGNORE INTO events VALUES (?, ?)',
                                         (record['event_id'], json.dumps(record)))
            if cursor.rowcount:
                self._apply(record)
                self.condition.notify_all()

    def _apply(self, event):
        self.revision += 1
        session = event.get('session_id') or 'unknown-session'
        turn = event.get('turn_id')
        kind = event.get('event_type')
        if not turn or kind not in ('user_message', 'tool_call', 'tool_result', 'assistant_message'):
            return
        key = (session, turn)
        if key not in self.turns:
            order = self.sessions.setdefault(session, [])
            self.turns[key] = {'session_id': session, 'turn_id': turn,
                               'depth': len(order) * 3, 'actions': [], 'person': None, 'final': None}
            order.append(key)
        state = self.turns[key]
        base = {'session_id': session, 'turn_id': turn}
        if kind in ('user_message', 'assistant_message'):
            role = 'person' if kind == 'user_message' else 'final'
            identifier = node_id(session, turn, role)
            state[role] = identifier
            self.nodes[identifier] = dict(base, id=identifier,
                type='PERSON' if role == 'person' else 'AI FINAL RESPONSE',
                depth=state['depth'] + (0 if role == 'person' else 2),
                label=event.get('message', ''), event=event)
        else:
            call = event.get('tool_call_id') or event['event_id']
            changes = event.get('file_changes') or []
            # A tool invocation may change many files: each is a separate action.
            items = changes if changes else [None]
            for index, change in enumerate(items):
                identifier = node_id(session, turn, call, change['path'] if change else 'tool', index)
                previous = self.nodes.get(identifier)
                if previous and previous['event']['event_type'] == 'tool_result' and kind == 'tool_call':
                    continue
                label = (change['operation'] + ' ' + Path(change['path']).name) if change else event.get('tool_name', 'Tool')
                self.nodes[identifier] = dict(base, id=identifier, type='AI ACTION',
                    depth=state['depth'] + 1, label=label, tool_call_id=call,
                    file_change=change, event=event)
                if identifier not in state['actions']:
                    state['actions'].append(identifier)

    def snapshot(self):
        with self.condition:
            edges = []
            def link(source, target):
                if source and target:
                    edges.append({'source': source, 'target': target})
            for order in self.sessions.values():
                previous = None
                for key in order:
                    turn = self.turns[key]
                    link(previous, turn['person'])
                    for action in turn['actions']:
                        link(turn['person'], action)
                        link(action, turn['final'])
                    if not turn['actions']:
                        link(turn['person'], turn['final'])
                    previous = turn['final']
            return {'revision': self.revision, 'nodes': list(self.nodes.values()),
                    'edges': edges, 'sessions': list(self.sessions)}

    def wait(self, revision, timeout=15):
        with self.condition:
            self.condition.wait_for(lambda: self.revision != revision, timeout)
            return self.snapshot() if self.revision != revision else None
