import unittest

from dotvectordb.construction_prompts.ConversationMemoryPrompts import DEFAULT_CHATGPT_ACTION_TYPES
from events.action_types import action_type_for_item, normalize_action_type, LIBRARY_ACTION_TYPES


class ActionTypeTests(unittest.TestCase):
    def test_each_protocol_item_maps_to_a_registered_library_type(self):
        expected = {
            'userMessage': 'human_input', 'hookPrompt': 'human_input',
            'agentMessage': 'assistant_partial_response',
            'functionCallOutput': 'tool_result', 'plan': 'assistant_plan',
            'reasoning': 'reasoning_summary', 'commandExecution': 'command_execution',
            'fileChange': 'file_change', 'mcpToolCall': 'mcp_tool_call',
            'dynamicToolCall': 'dynamic_tool_call', 'collabAgentToolCall': 'agent_collaboration',
            'subAgentActivity': 'agent_collaboration', 'webSearch': 'web_search',
            'imageView': 'image_view', 'sleep': 'dynamic_tool_call',
            'imageGeneration': 'dynamic_tool_call', 'enteredReviewMode': 'review_started',
            'exitedReviewMode': 'review_completed', 'contextCompaction': 'context_compaction',
        }
        for kind, role in expected.items():
            for spelling in (kind, kind[0].upper() + kind[1:]):
                with self.subTest(kind=spelling):
                    self.assertEqual(action_type_for_item({'type': spelling}), role)
                    self.assertIn(role, DEFAULT_CHATGPT_ACTION_TYPES)

    def test_web_actions_and_extension_variants(self):
        for action, role in [('search', 'web_search'), ('open_page', 'web_open'),
                             ('openPage', 'web_open'), ('find_in_page', 'web_find'),
                             ('findInPage', 'web_find'), ('other', 'web_search')]:
            self.assertEqual(action_type_for_item({
                'type': 'WebSearch', 'action': {'type': action}}), role)
        for name, role in [('web.search', 'web_search'), ('web.open', 'web_open'),
                           ('web.find', 'web_find')]:
            self.assertEqual(action_type_for_item({'type': 'Extension', 'kind': name}), role)
            self.assertEqual(normalize_action_type(name), role)

    def test_agent_phase_and_canonical_types(self):
        for phase, role in [('commentary', 'assistant_commentary'),
                            ('final_answer', 'assistant_response'),
                            (None, 'assistant_partial_response')]:
            self.assertEqual(action_type_for_item({'type': 'AgentMessage', 'phase': phase}), role)
        self.assertEqual(LIBRARY_ACTION_TYPES, DEFAULT_CHATGPT_ACTION_TYPES.keys())
        for role in DEFAULT_CHATGPT_ACTION_TYPES:
            self.assertEqual(normalize_action_type(role), role)

    def test_undefined_types_and_variants_are_rejected_without_fallback(self):
        for item in ({'type': 'FutureTool'}, {'type': 'Extension', 'kind': 'future.tool'},
                     {'type': 'WebSearch', 'action': {'type': 'future'}},
                     {'type': 'AgentMessage', 'phase': 'future'}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                action_type_for_item(item)
        with self.assertRaises(ValueError):
            normalize_action_type('unregistered')
