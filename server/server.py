#!/usr/bin/env python3
"""Receive Codex hook events and print them. No third-party dependencies."""
import argparse
import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from events import normalize, FileSnapshots
from graph import Graph

PRINT_LOCK = threading.Lock()
MAX_BODY = 16 * 1024 * 1024
SNAPSHOTS = FileSnapshots()


def display(event, graph=None):
    record = normalize(event)
    with PRINT_LOCK:
        SNAPSHOTS.enrich(record)
        if graph is not None:
            graph.ingest(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            body = Path(__file__).with_name('index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/api/graph':
            self.reply(200, self.server.graph.snapshot())
            return
        if self.path == '/api/stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            revision = -1
            try:
                while True:
                    snapshot = self.server.graph.wait(revision)
                    if snapshot is None:
                        self.wfile.write(b': heartbeat\n\n')
                    else:
                        revision = snapshot['revision']
                        self.wfile.write(('data: ' + json.dumps(snapshot) + '\n\n').encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return
        self.reply(200 if self.path == "/health" else 404,
                   {"ok": True} if self.path == "/health" else {"error": "not found"})

    def do_POST(self):
        if self.path != "/events":
            self.reply(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.reply(413, {"error": "body must be between 1 byte and 16 MiB"})
                return
            self.connection.settimeout(5)
            event = json.loads(self.rfile.read(length))
            if not isinstance(event, dict):
                raise ValueError("expected a JSON object")
        except (ValueError, OSError):
            self.reply(400, {"error": "invalid JSON event"})
            return
        display(event, self.server.graph)
        self.reply(200, {"ok": True})

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument('--database', default=str(Path(__file__).with_name('graph.sqlite3')),
                        help='SQLite event history path (use :memory: for temporary history)')
    args = parser.parse_args()
    with ThreadingHTTPServer((args.host, args.port), Handler) as server:
        server.graph = Graph(args.database)
        import sys
        print(f"Listening on http://{args.host}:{server.server_port}/events (Ctrl+C to stop)", file=sys.stderr, flush=True)
        print(f"Live graph: http://{args.host}:{server.server_port}/", file=sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
