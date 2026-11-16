"""Asynchronous Codex hook receiver and live graph HTTP interface."""
import asyncio
import json
import sys
from pathlib import Path

from aiohttp import web

from events.events import normalize, message_id, FileSnapshots
from knowledge_graph.CodexInteractionGraph import CodexInteractionGraph

MAX_BODY = 16 * 1024 * 1024


class EventServer:
    """Serve hook events and live graph updates on one asyncio loop."""

    def __init__(self, graph, revision):
        self.graph = graph
        self.revision = revision
        self.condition = asyncio.Condition()
        self.snapshots = FileSnapshots()
        self.pending_messages = {}

    def application(self):
        """Build the HTTP application with a bounded event body size."""
        app = web.Application(client_max_size=MAX_BODY)
        app.add_routes([
            web.get('/', self.index),
            web.get('/api/graph', self.snapshot),
            web.get('/api/stream', self.stream),
            web.get('/health', self.health),
            web.post('/events', self.receive),
        ])
        return app

    async def index(self, request):
        """Serve the graph interface."""
        return web.FileResponse(Path(__file__).parent.parent / 'front_end' / 'index.html')

    async def health(self, request):
        """Report that the receiver is listening."""
        return web.json_response({'ok': True})

    async def snapshot(self, request):
        """Read the cached graph without overlapping an ingestion."""
        async with self.condition:
            return web.json_response(await self.graph.snapshot())

    async def receive(self, request):
        """Normalize and persist an event, then notify live subscribers."""
        try:
            body = await asyncio.wait_for(request.read(), timeout=5)
            if not body:
                return web.json_response({'error': 'invalid JSON event'}, status=400)
            event = json.loads(body)
            if not isinstance(event, dict):
                raise ValueError('expected a JSON object')
        except (ValueError, UnicodeDecodeError, asyncio.TimeoutError):
            return web.json_response({'error': 'invalid JSON event'}, status=400)
        async with self.condition:
            record = normalize(event)
            self.snapshots.enrich(record)
            for key, pending in list(self.pending_messages.items()):
                pending['message_id'] = message_id(pending['raw_event'])
                if pending['message_id']:
                    await self.graph.ingest(pending)
                    del self.pending_messages[key]
            if record['event_type'] in ('user_message', 'assistant_message') and not record['message_id']:
                key = (record['session_id'], record['turn_id'], record['event_type'])
                self.pending_messages[key] = record
            else:
                await self.graph.ingest(record)
            self.revision = (await self.graph.snapshot())['revision']
            self.condition.notify_all()
            print(json.dumps(record, ensure_ascii=False), flush=True)
        return web.json_response({'ok': True})

    async def stream(self, request):
        """Stream graph revisions while yielding between updates and heartbeats."""
        response = web.StreamResponse(headers={
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
        })
        await response.prepare(request)
        revision = None
        try:
            while True:
                async with self.condition:
                    try:
                        await asyncio.wait_for(
                            self.condition.wait_for(lambda: self.revision != revision),
                            timeout=15,
                        )
                        snapshot = await self.graph.snapshot()
                    except asyncio.TimeoutError:
                        snapshot = None
                if snapshot is None:
                    await response.write(b': heartbeat\n\n')
                else:
                    revision = snapshot['revision']
                    await response.write(('data: ' + json.dumps(snapshot) + '\n\n').encode())
        except (ConnectionError, OSError):
            pass
        return response


    @classmethod
    async def run(cls, host, port, database):
        """Manage conversation memory and HTTP server startup and shutdown."""
        async with CodexInteractionGraph(database) as graph:
            receiver = cls(graph, (await graph.snapshot())['revision'])
            runner = web.AppRunner(receiver.application(), shutdown_timeout=1)
            await runner.setup()
            try:
                site = web.TCPSite(runner, host, port)
                await site.start()
                print(f'Listening on http://{host}:{port}/events (Ctrl+C to stop)',
                      file=sys.stderr, flush=True)
                print(f'Live graph: http://{host}:{port}/', file=sys.stderr, flush=True)
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
