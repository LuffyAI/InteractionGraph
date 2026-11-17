import asyncio
import json
import unittest
import tempfile
from pathlib import Path
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
                'message_id': 'native-message',
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

    async def test_slow_description_does_not_block_hooks_and_publishes_when_ready(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def describe(notify):
            started.set()
            await finish.wait()
            self.state['revision'] = 'summary-ready'
            await notify()
        self.graph.describe_pending.side_effect = describe
        stream = await self.client.get('/api/stream')
        await stream.content.readline()
        await stream.content.readline()
        with patch('builtins.print'):
            response = await self.client.post('/events', json={
                'hook_event_name': 'UserPromptSubmit', 'session_id': 'test',
                'turn_id': 'turn', 'message_id': 'prompt', 'prompt': 'hello'})
        self.assertEqual(response.status, 200)
        await asyncio.wait_for(started.wait(), 1)
        health = await asyncio.wait_for(self.client.get('/health'), 1)
        self.assertEqual(health.status, 200)
        snapshot = await asyncio.wait_for(self.client.get('/api/graph'), 1)
        self.assertEqual((await snapshot.json())['revision'], 'initial')
        finish.set()
        update = await asyncio.wait_for(stream.content.readline(), 1)
        self.assertEqual(json.loads(update.decode()[6:])['revision'], 'summary-ready')
        stream.close()

    async def test_prompt_waits_for_native_message_id_before_ingestion(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / 'transcript.jsonl'
            transcript.touch()
            prompt = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'test',
                      'turn_id': 'turn', 'prompt': 'hello', 'transcript_path': str(transcript)}
            with patch('builtins.print'):
                response = await self.client.post('/events', json=prompt)
            self.assertEqual(response.status, 200)
            self.graph.ingest.assert_not_awaited()
            self.assertEqual(len(self.receiver.pending_messages), 1)
            transcript.write_text(json.dumps({'payload': {'turn_id': 'turn', 'item': {
                'type': 'UserMessage', 'id': 'native-prompt-id',
            }}}) + '\n')
            with patch('builtins.print'):
                response = await self.client.post('/events', json={
                    'hook_event_name': 'Stop', 'session_id': 'test', 'turn_id': 'turn',
                    'message_id': 'native-answer-id', 'last_assistant_message': 'hello back',
                })
            self.assertEqual(response.status, 200)
            records = [call.args[0] for call in self.graph.ingest.await_args_list]
            self.assertEqual([record['message_id'] for record in records],
                             ['native-prompt-id', 'native-answer-id'])
            self.assertEqual(self.receiver.pending_messages, {})
