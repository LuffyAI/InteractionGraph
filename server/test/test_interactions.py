import json
import unittest
from unittest.mock import AsyncMock, patch

from dotvectordb.plugins.hash_functions.hashfuncs import SHA256HashingFunc
from dotvectordb.ConversationMemoryTree import ConversationMemoryTree
from dotvectordb.construction_prompts.ConversationMemoryPrompts import DEFAULT_CHATGPT_ACTION_TYPES
from knowledge_graph.CodexInteractionGraph import CodexInteractionGraph


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.object(ConversationMemoryTree, '__init__', return_value=None):
            self.graph = CodexInteractionGraph('memory')
        self.graph.hashing_func = SHA256HashingFunc()
        self.hash = self.graph.hashing_func.content_hash
        self.rows, self.actions = [], []
        self.graph.get_conversation = AsyncMock(side_effect=lambda session: {
            'conversation_id': session, 'interaction_depth': 7, 'global_interaction_count': len(self.rows)})
        self.graph.add_conversation = AsyncMock()
        self.graph.get_action_types = AsyncMock(return_value=DEFAULT_CHATGPT_ACTION_TYPES)
        self.graph.get_all_interactions = AsyncMock(side_effect=lambda conversation: [r for r in self.rows if r['conversation_id'] == conversation])
        self.graph.get_all_actions = AsyncMock(side_effect=lambda conversation: [
            a for a in self.actions if any(r['conversation_id'] == conversation
                                           and r['interaction_id'] == a['src_interaction'] for r in self.rows)])
        self.graph.get_incident_edges_of_important_node = AsyncMock(side_effect=lambda identifier: [
            a for a in self.actions if identifier in (a['src_interaction'], a['dst_interaction'])])
        async def add_interaction(identifier, conversation, role, content):
            self.rows.append({'interaction_id': identifier, 'conversation_id': conversation,
                              'action_type': role, 'content': content,
                              'interaction_number': len(self.rows)+1, 'interaction_depth': 7})
        async def add_action(identifier, source, target, role):
            self.actions.append({'action_id': len(self.actions)+1,
                                 'src_interaction': source, 'dst_interaction': target, 'action_type': role})
        self.graph.add_interaction = AsyncMock(side_effect=add_interaction)
        self.graph.add_action = AsyncMock(side_effect=add_action)

    def event(self, kind, **kwargs):
        return dict(session_id='session-id', turn_id='turn-id', event_id=kind,
                    event_type=kind, message_id='message-'+kind, message=kind,
                    action_type='command_execution', **kwargs)

    async def test_pending_actions_only_save_when_finished(self):
        await self.graph.ingest(self.event('user_message'))
        changes = [{'path':'a.py', 'operation':'add'}, {'path':'b.py', 'operation':'add'}]
        await self.graph.ingest(self.event('tool_call', tool_call_id='codex-call', file_changes=changes))
        graph = await self.graph.snapshot()
        self.assertEqual(len(graph['nodes']), 3)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(graph['edges']), 0)
        self.assertTrue(all(n['depth'] == 7 for n in graph['nodes']))
        await self.graph.ingest(self.event('tool_result', tool_call_id='codex-call', file_changes=changes))
        self.assertEqual(len(self.rows), 3)
        self.assertEqual(self.graph.pending, {})
        await self.graph.ingest(self.event('assistant_message'))
        graph = await self.graph.snapshot()
        self.assertEqual(len(graph['nodes']), 4)
        self.assertEqual(len(graph['edges']), 0)
        self.assertEqual(self.rows[0]['interaction_id'], self.hash('message-user_message'))
        self.assertTrue(all(r['conversation_id'] == self.hash('session-id') for r in self.rows))
        await self.graph.ingest(self.event('assistant_message'))
        self.assertEqual(len(self.rows), 4)
        self.graph.add_action.assert_not_awaited()

    async def test_creates_conversation_through_library(self):
        self.graph.get_conversation.side_effect = [None, {'interaction_depth':1}, {'interaction_depth':1, 'global_interaction_count':1}]
        await self.graph.ingest(self.event('user_message'))
        self.graph.add_conversation.assert_awaited_once_with(self.hash('session-id'))

    async def test_live_descriptions_use_default_llm_with_ordered_turn_context(self):
        self.graph.default_llm_func = AsyncMock(side_effect=[
            ({'current_prompt_interpretation': 'Build the feature'}, 1, 1, 0),
            ({'current_action_summary': 'Updated the file'}, 1, 1, 0),
            ({'TaskClarity': []}, 1, 1, 0),
        ])
        async def describe(conversation, identifier, callback):
            row = next(r for r in self.rows if r['interaction_id'] == identifier)
            return await callback(row)
        self.graph.describe_interaction = AsyncMock(side_effect=describe)
        notify = AsyncMock()
        await self.graph.ingest(self.event('user_message'))
        await self.graph.ingest(self.event('tool_call', tool_call_id='call'))
        before = await self.graph.snapshot()
        await self.graph.describe_pending(notify)
        self.assertEqual(self.graph.describe_interaction.await_count, 1)
        await self.graph.ingest(self.event('tool_result', tool_call_id='call'))
        await self.graph.ingest(self.event('assistant_message'))
        await self.graph.describe_pending(notify)
        calls = self.graph.default_llm_func.await_args_list
        self.assertEqual(calls[0].args[0]['action_type'], 'human_input')
        self.assertEqual([r['action_type'] for r in calls[1].args[0]],
                         ['human_input', 'command_execution'])
        self.assertEqual([r['action_type'] for r in calls[2].args[0]],
                         ['human_input', 'command_execution', 'assistant_response'])
        after = await self.graph.snapshot()
        self.assertNotEqual(before['revision'], after['revision'])
        self.assertEqual(after['nodes'][1]['description']['current_action_summary'], 'Updated the file')
        self.assertTrue(all(n['description_status'] == 'ready' for n in after['nodes']))
        await self.graph.ingest(self.event('assistant_message'))
        await self.graph.describe_pending(notify)
        self.assertEqual(self.graph.describe_interaction.await_count, 3)

    async def test_description_failure_preserves_node_and_continues(self):
        await self.graph.ingest(self.event('user_message'))
        self.graph.describe_interaction = AsyncMock(side_effect=RuntimeError('provider unavailable'))
        with self.assertLogs(level='ERROR'):
            await self.graph.describe_pending(AsyncMock())
        snapshot = await self.graph.snapshot()
        self.assertEqual(len(snapshot['nodes']), 1)
        self.assertEqual(snapshot['nodes'][0]['description_status'], 'error')

    async def test_load_restores_saved_description(self):
        await self.graph.ingest(self.event('user_message'))
        self.rows[0]['is_described'] = True
        self.graph._rows.clear()
        self.graph.get_interaction_description = AsyncMock(return_value={
            'description': json.dumps({'current_prompt_interpretation': 'Saved summary'})})
        snapshot = await self.graph.snapshot('session-id')
        self.assertEqual(snapshot['nodes'][0]['description']['current_prompt_interpretation'], 'Saved summary')

    async def test_repeated_snapshots_and_ingestion_do_not_reload_history(self):
        await self.graph.ingest(self.event('user_message'))
        await self.graph.snapshot()
        await self.graph.snapshot()
        await self.graph.ingest(self.event('tool_call', tool_call_id='call'))
        await self.graph.snapshot()
        await self.graph.ingest(self.event('tool_result', tool_call_id='call'))
        snapshot = await self.graph.snapshot()
        self.graph.get_all_interactions.assert_awaited_once_with(self.hash('session-id'))
        self.graph.get_all_actions.assert_not_awaited()
        self.assertEqual(len(snapshot['nodes']), 2)
        self.assertEqual(len(snapshot['edges']), 0)
        self.assertEqual(snapshot['nodes'][0]['depth'], 7)

    async def test_each_chat_loads_once_and_snapshots_stay_separate(self):
        await self.graph.ingest(self.event('user_message'))
        other = dict(self.event('user_message'), session_id='other-chat', message_id='other-message')
        await self.graph.ingest(other)
        first = await self.graph.snapshot('session-id')
        second = await self.graph.snapshot('other-chat')
        await self.graph.snapshot('session-id')
        self.assertEqual([n['id'] for n in first['nodes']], [str(self.hash('message-user_message'))])
        self.assertEqual([n['id'] for n in second['nodes']], [str(self.hash('other-message'))])
        self.assertEqual(self.graph.get_all_interactions.await_count, 2)
        self.graph.get_all_actions.assert_not_awaited()
        self.assertEqual([c.args for c in self.graph.get_all_interactions.await_args_list],
                         [(self.hash('session-id'),), (self.hash('other-chat'),)])

    async def test_uses_registered_types_without_guessing_from_tool_name(self):
        event = self.event('tool_result', tool_call_id='native-call', tool_name='anything')
        event['action_type'] = 'agent_collaboration'
        await self.graph.ingest(event)
        self.assertEqual(self.rows[0]['action_type'], 'agent_collaboration')
        event = dict(event, tool_call_id='unknown-call', action_type='unregistered')
        with self.assertRaisesRegex(ValueError, 'not registered'):
            await self.graph.ingest(event)
        self.assertEqual(len(self.rows), 1)

    async def test_loading_uses_stored_incident_edges_without_inference(self):
        for identifier, role, kind in [('human', 'human_input', 'human_input'),
                                       ('middle', 'command_execution', 'command_execution'),
                                       ('answer', 'assistant_response', 'assistant_response')]:
            node = {'id':str(self.hash(identifier)), 'label':identifier, 'session_id':'stored',
                    'turn_id':identifier, 'event':{'event_id':identifier}, 'action_type':role}
            self.rows.append({'interaction_id':self.hash(identifier), 'conversation_id':self.hash('stored'),
                              'action_type':role, 'content':json.dumps(node),
                              'interaction_number':len(self.rows)+1, 'interaction_depth':1})
        self.actions.extend([
            {'action_id':1, 'src_interaction':self.hash('human'), 'dst_interaction':self.hash('middle')},
            {'action_id':2, 'src_interaction':self.hash('middle'), 'dst_interaction':self.hash('answer')}])
        graph = await self.graph.snapshot('stored')
        self.assertEqual(graph['edges'], [{'source':str(self.hash('human')), 'target':str(self.hash('middle'))},
                                          {'source':str(self.hash('middle')), 'target':str(self.hash('answer'))}])
        self.assertEqual([c.args for c in self.graph.get_incident_edges_of_important_node.await_args_list],
                         [(self.hash('human'),), (self.hash('answer'),)])
        self.graph.add_action.assert_not_awaited()
        await self.graph.snapshot('stored')
        self.assertEqual(self.graph.get_incident_edges_of_important_node.await_count, 2)

    async def test_hashes_native_ids_to_sqlite_integers_and_keeps_original_event(self):
        event = self.event('user_message')
        event.update(session_id='01a1cc62-6087-74e2-a5fa-dd4c23cd1554',
                     message_id='msg_native_codex_id')
        await self.graph.ingest(event)
        identifier, conversation, _, content = self.graph.add_interaction.await_args.args
        self.assertEqual(identifier, self.hash(event['message_id']))
        self.assertEqual(conversation, self.hash(event['session_id']))
        for value in (identifier, conversation):
            self.assertIsInstance(value, int)
            self.assertTrue(-(2 ** 63) <= value < 2 ** 63)
        self.assertEqual(json.loads(content)['event'], event)
        self.graph.get_incident_edges_of_important_node.assert_awaited_once_with(identifier)
