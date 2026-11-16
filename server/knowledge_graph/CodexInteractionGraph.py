"""Live presentation of Codex events stored through ConversationMemoryTree."""
import json
from pathlib import Path
from dotvectordb.ConversationMemoryTree import ConversationMemoryTree

class CodexInteractionGraph(ConversationMemoryTree):
    def __init__(self, *args, **kwargs):
        """Keep inherited settings and initialize per-chat UI caches and pending actions."""
        super().__init__(*args, **kwargs)
        self.pending = {}
        self._rows = {}
        self._actions = {}
        self._registered_types = None

    async def load(self, conversation_id):
        """Load a chat's ordered interactions and edges once through the library getters."""
        if self._registered_types is None:
            self._registered_types = await self.get_action_types()
        if conversation_id not in self._rows:
            rows = await self.get_all_interactions(self.hashing_func.content_hash(conversation_id))
            self._rows[conversation_id] = {str(row['interaction_id']): row for row in rows}
            self._actions[conversation_id] = {}
            for row in rows:
                if row['action_type'] in ('human_input', 'assistant_response'):
                    await self._load_incident_edges(conversation_id, row['interaction_id'])

    async def _load_incident_edges(self, session, interaction_id):
        """Cache stored edges incident to a human-input or answer node."""
        for edge in await self.get_incident_edges_of_important_node(interaction_id):
            pair = (str(edge['src_interaction']), str(edge['dst_interaction']))
            self._actions[session][pair] = edge

    async def ingest(self, event):
        """Coordinate event validation, loading, storage, and stored-edge refreshes."""
        if not self._supports_event(event):
            return
        session = event['session_id']
        await self.load(session)
        conversation = await self._get_or_create_conversation(session)
        entries = self._build_entries(event)
        await self._store_entries(event, entries, conversation)
        if event['event_type'] != 'tool_call':
            await self._refresh_important_nodes(session, entries)

    @staticmethod
    def _supports_event(event):
        """Accept supported events with Codex session and turn identifiers."""
        return bool(event.get('session_id') and event.get('turn_id') and
                    event.get('event_type') in (
                        'user_message', 'assistant_message', 'tool_call', 'tool_result'))

    async def _get_or_create_conversation(self, session):
        """Find or create this chat using the library's hash of its Codex ID."""
        conversation_id = self.hashing_func.content_hash(session)
        conversation = await self.get_conversation(conversation_id)
        if conversation is None:
            await self.add_conversation(conversation_id)
            conversation = await self.get_conversation(conversation_id)
        return conversation

    @staticmethod
    def _build_entries(event):
        """Prepare message entries or one action entry per changed file."""
        kind = event['event_type']
        if kind in ('user_message', 'assistant_message'):
            message_id = event.get('message_id')
            if not message_id:
                raise ValueError('Codex message_id is missing.')
            role = 'human_input' if kind == 'user_message' else 'assistant_response'
            entries = [(message_id, role, {
                'label': event.get('message', ''),
            })]
        else:
            call_id = event.get('tool_call_id')
            if not call_id:
                raise ValueError('Codex tool_call_id is missing.')
            entries = []
            for index, change in enumerate(event.get('file_changes') or [None]):
                role = 'file_change' if change else event.get('action_type')
                entries.append((f'{call_id}:{index}' if change else call_id, role, {
                    'tool_call_id': call_id, 'file_change': change,
                    'label': change['operation'] + ' ' + Path(change['path']).name
                    if change else event.get('tool_name', 'Tool'),
                }))

        return entries

    async def _store_entries(self, event, entries, conversation):
        """Keep pending actions in memory and save finished interactions once."""
        session, kind = event['session_id'], event['event_type']
        conversation_id = self.hashing_func.content_hash(session)
        saved = self._rows[session]
        for interaction_id, role, payload in entries:
            stored_id = self.hashing_func.content_hash(interaction_id)
            interaction_id = str(stored_id)
            node = dict(payload, id=interaction_id, session_id=session,
                        turn_id=event['turn_id'], event=event, action_type=role)
            if interaction_id in saved:
                continue
            if kind == 'tool_call':
                self.pending[(session, interaction_id)] = dict(
                    node, depth=conversation['interaction_depth'])
                continue
            if role not in self._registered_types:
                raise ValueError(f'Codex action type {role!r} is not registered in ConversationMemoryTree.')
            await self.add_interaction(stored_id, conversation_id, role, json.dumps(node))
            depth = conversation['interaction_depth']
            conversation = await self.get_conversation(conversation_id)
            self._rows[session][interaction_id] = {
                'interaction_id': stored_id, 'conversation_id': conversation_id,
                'interaction_number': conversation['global_interaction_count'],
                'interaction_depth': depth, 'action_type': role, 'content': json.dumps(node),
            }
            self.pending.pop((session, interaction_id), None)

    async def _refresh_important_nodes(self, session, entries):
        """Read existing incident edges for important nodes; never create connections."""
        for interaction_id, role, _ in entries:
            if role in ('human_input', 'assistant_response'):
                await self._load_incident_edges(session, self.hashing_func.content_hash(interaction_id))

    async def snapshot(self, conversation_id=None):
        """Return UI nodes and edges for one chat or all currently loaded chats.

        Use cached rows with the library's stored depth, include unsaved pending
        actions, and provide a revision value for detecting live view changes.
        An explicitly requested chat is loaded only if it is not already cached.
        """
        if conversation_id is not None:
            await self.load(conversation_id)
        sessions = [conversation_id] if conversation_id is not None else list(self._rows)
        rows = [row for session in sessions for row in self._rows[session].values()]
        nodes = []
        for row in rows:
            node = json.loads(row['content'])
            node['depth'] = row['interaction_depth']
            nodes.append(node)
        saved_ids = {n['id'] for n in nodes}
        nodes.extend(n for n in self.pending.values() if n['session_id'] in sessions and n['id'] not in saved_ids)
        edges = [{'source': str(a['src_interaction']), 'target': str(a['dst_interaction'])}
                 for session in sessions for a in self._actions[session].values()]
        return {
            'revision': json.dumps([[n['event']['event_id'] for n in nodes], edges], sort_keys=True),
            'nodes': nodes, 'edges': edges,
            'sessions': list(dict.fromkeys(n['session_id'] for n in nodes)),
        }
