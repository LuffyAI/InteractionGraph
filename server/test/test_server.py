import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from events.EventServer import EventServer


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = {'revision': 'initial', 'nodes': [], 'edges': [], 'sessions': []}
        self.graph = AsyncMock()
        self.graph.snapshot.side_effect = lambda: dict(self.state)
        self.receiver = EventServer(self.graph, 'initial')
        self.client = TestClient(TestServer(self.receiver.application()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_stream_receives_ingested_update_without_blocking_requests(self):
        stream = await self.client.get('/api/stream')
        initial = await asyncio.wait_for(stream.content.readline(), 1)
        self.assertEqual(json.loads(initial.decode()[6:])['revision'], 'initial')
        await stream.content.readline()
        health = await self.client.get('/health')
        self.assertEqual(await health.json(), {'ok': True})

        async def ingest(record):
            self.state['revision'] = 'updated'

        self.graph.ingest.side_effect = ingest
        with patch('builtins.print'):
            response = await self.client.post('/events', json={
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'test', 'prompt': 'hello',
            })
        self.assertEqual(response.status, 200)
        update = await asyncio.wait_for(stream.content.readline(), 1)
        self.assertEqual(json.loads(update.decode()[6:])['revision'], 'updated')
        self.graph.ingest.assert_awaited_once()
        snapshot = await self.client.get('/api/graph')
        self.assertEqual((await snapshot.json())['revision'], 'updated')
        stream.close()

    async def test_invalid_and_oversized_events_are_not_ingested(self):
        for body in ('[]', '{broken', ''):
            response = await self.client.post('/events', data=body)
            self.assertEqual(response.status, 400)
        with patch('events.EventServer.MAX_BODY', 8):
            small_client = TestClient(TestServer(self.receiver.application()))
        async with small_client:
            response = await small_client.post('/events', data='x' * 9)
            self.assertEqual(response.status, 413)
        self.graph.ingest.assert_not_awaited()
