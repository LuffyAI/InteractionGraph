import tempfile
import unittest
from pathlib import Path

from events import normalize
from graph import Graph


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'graph.sqlite3'
        self.graph = Graph(self.path)

    def tearDown(self):
        self.graph.close()
        self.directory.cleanup()

    def event(self, hook, **kwargs):
        return normalize(dict(session_id='s', turn_id='t', hook_event_name=hook, **kwargs))

    def test_diamond_one_action_per_file_and_replay(self):
        prompt = self.event('UserPromptSubmit', prompt='create two files')
        self.graph.ingest(prompt)
        self.graph.ingest(prompt)
        patch = '*** Begin Patch\n*** Add File: a.py\n+a=1\n*** Add File: b.py\n+b=2\n*** End Patch'
        for hook in ('PreToolUse', 'PostToolUse'):
            self.graph.ingest(self.event(hook, tool_name='apply_patch', tool_use_id='call',
                                        tool_input={'command': patch}, tool_response={'exit_code': 0}))
        self.graph.ingest(self.event('Stop', last_assistant_message='done'))
        data = self.graph.snapshot()
        self.assertEqual(len(data['nodes']), 4)
        self.assertEqual(len(data['edges']), 4)
        actions = [n for n in data['nodes'] if n['type'] == 'AI ACTION']
        self.assertEqual([n['depth'] for n in actions], [1, 1])
        self.assertEqual({n['file_change']['path'] for n in actions}, {'a.py', 'b.py'})
        self.assertTrue(all(n['event']['event_type'] == 'tool_result' for n in actions))
        self.graph.close()
        self.graph = Graph(self.path)
        self.assertEqual(self.graph.snapshot(), data)

    def test_turn_depth_and_session_isolation(self):
        self.graph.ingest(self.event('UserPromptSubmit', prompt='hello'))
        self.graph.ingest(self.event('Stop', last_assistant_message='hi'))
        self.graph.ingest(normalize({'session_id': 's', 'turn_id': 't2',
                                    'hook_event_name': 'UserPromptSubmit', 'prompt': 'next'}))
        self.graph.ingest(normalize({'session_id': 'other', 'turn_id': 't',
                                    'hook_event_name': 'UserPromptSubmit', 'prompt': 'separate'}))
        data = self.graph.snapshot()
        self.assertEqual([n['depth'] for n in data['nodes']], [0, 2, 3, 0])
        self.assertEqual(len(data['edges']), 2)
        ids = {n['id']: n for n in data['nodes']}
        self.assertTrue(all(ids[e['source']]['session_id'] == ids[e['target']]['session_id'] for e in data['edges']))

    def test_final_before_tool_and_reordered_pre_result(self):
        self.graph.ingest(self.event('Stop', last_assistant_message='done'))
        self.graph.ingest(self.event('PostToolUse', tool_use_id='c', tool_name='Bash', tool_response={'exit_code': 0}))
        self.graph.ingest(self.event('PreToolUse', tool_use_id='c', tool_name='Bash'))
        self.graph.ingest(self.event('UserPromptSubmit', prompt='run'))
        data = self.graph.snapshot()
        self.assertEqual(len(data['nodes']), 3)
        self.assertEqual(len(data['edges']), 2)
        action = next(n for n in data['nodes'] if n['type'] == 'AI ACTION')
        self.assertEqual(action['event']['event_type'], 'tool_result')


if __name__ == '__main__':
    unittest.main()
