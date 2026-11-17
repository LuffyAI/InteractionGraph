import unittest
import json
import tempfile
from pathlib import Path

from events.events import normalize, patch_changes, FileSnapshots


class EventTests(unittest.TestCase):
    def test_dotted_action_types_use_library_names(self):
        for action in ('search', 'open', 'find'):
            raw = {'hook_event_name': 'PostToolUse', 'action_type': f'web.{action}'}
            self.assertEqual(normalize(raw)['action_type'], f'web_{action}')
            self.assertEqual(raw['action_type'], f'web.{action}')
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / 'conversation.jsonl'
            transcript.write_text(json.dumps({'payload': {'turn_id': 'turn', 'item': {
                'id': 'call', 'type': 'Extension', 'kind': 'web.search',
            }}}) + '\n')
            record = normalize({'hook_event_name': 'PostToolUse', 'turn_id': 'turn',
                                'tool_use_id': 'call', 'transcript_path': str(transcript)})
            self.assertEqual(record['action_type'], 'web_search')

    def test_native_message_ids_from_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            transcript = Path(directory) / 'conversation.jsonl'
            items = [('UserMessage', 'native-user-id', None),
                     ('AgentMessage', 'commentary-id', 'commentary'),
                     ('AgentMessage', 'native-final-id', 'final_answer')]
            transcript.write_text(''.join(json.dumps({'type': 'event_msg', 'payload': {
                'turn_id': 'turn', 'item': {'type': kind, 'id': identifier, 'phase': phase}}}) + '\n'
                for kind, identifier, phase in items))
            common = {'turn_id': 'turn', 'transcript_path': str(transcript)}
            self.assertEqual(normalize(dict(common, hook_event_name='UserPromptSubmit'))['message_id'], 'native-user-id')
            self.assertEqual(normalize(dict(common, hook_event_name='Stop'))['message_id'], 'native-final-id')
            self.assertEqual(normalize({'hook_event_name': 'Stop', 'message_id': 'provided-id'})['message_id'], 'provided-id')

    def test_snapshot_file_line_numbers_and_no_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'a.py'
            path.write_text('first\nold\nlast\n')
            event = {'hook_event_name': 'PreToolUse', 'session_id': 's',
                     'turn_id': 't', 'tool_use_id': 'call', 'cwd': directory,
                     'tool_name': 'apply_patch', 'tool_input': {'command':
                         '*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n+extra\n*** End Patch'}}
            tracker = FileSnapshots()
            tracker.enrich(normalize(event))
            path.write_text('first\nnew\nextra\nlast\n')
            event['hook_event_name'] = 'PostToolUse'
            record = normalize(event)
            tracker.enrich(record)
            change = record['file_changes'][0]
            self.assertEqual(change['line_changes_source'], 'filesystem_snapshots')
            self.assertEqual(change['line_changes'], [
                {'type': 'removed', 'text': 'old', 'old_line': 2, 'new_line': None},
                {'type': 'added', 'text': 'new', 'old_line': None, 'new_line': 2},
                {'type': 'added', 'text': 'extra', 'old_line': None, 'new_line': 3}])
            event['hook_event_name'] = 'PreToolUse'
            tracker.enrich(normalize(event))
            event['hook_event_name'] = 'PostToolUse'
            record = normalize(event)
            tracker.enrich(record)
            self.assertEqual(record['file_changes'][0]['line_changes'], [])
            self.assertFalse(record['file_changes'][0]['content_changed'])

    def test_exact_line_changes(self):
        changes = patch_changes('*** Begin Patch\n*** Update File: a.py\n@@ -10,2 +10,3 @@\n keep\n-old\n+new\n+\n*** Add File: b.py\n+hello\n*** End Patch')
        lines = changes[0]['line_changes']
        self.assertEqual(lines[0]['old_line'], 11)
        self.assertEqual(lines[1]['new_line'], 11)
        self.assertEqual(lines[2]['new_line'], 12)
        self.assertEqual(lines[2]['text'], '')
        self.assertEqual(changes[1]['line_changes'][0]['new_line'], 1)

    def test_unnumbered_hunks_do_not_guess_file_lines(self):
        lines = patch_changes('*** Begin Patch\n*** Update File: a.py\n@@\n context\n-old\n+new\n*** End Patch')[0]['line_changes']
        self.assertEqual(lines[0]['text'], 'old')
        self.assertIsNone(lines[0]['old_line'])
        self.assertIsNone(lines[1]['new_line'])
        self.assertEqual(lines[1]['hunk_line'], 2)

    def test_patch_excerpts_and_multiple_files(self):
        patch = """*** Begin Patch
*** Update File: app.py
@@ def greet():
-    return 'old'
+    return 'new'
 
@@ def other():
 keep()
-remove()
+replace()
*** Add File: new.py
+print('hello')
*** Delete File: gone.py
*** End Patch"""
        changes = patch_changes(patch)
        self.assertEqual([c['operation'] for c in changes], ['update', 'add', 'delete'])
        self.assertEqual(changes[0]['snippets'][0]['before'], "    return 'old'\n")
        self.assertEqual(changes[0]['snippets'][1]['after'], 'keep()\nreplace()')
        self.assertEqual(changes[1]['snippets'][0]['after'], "print('hello')")
        self.assertEqual(changes[2]['snippets'], [])

    def test_requested_patch_is_not_confirmed(self):
        event = normalize({'hook_event_name': 'PreToolUse', 'tool_name': 'apply_patch',
                           'tool_input': {'command': '*** Begin Patch\n*** Add File: a.py\n+x=1\n*** End Patch'}})
        self.assertEqual(event['change_stage'], 'requested')
        self.assertEqual(event['status'], '')
        self.assertEqual(event['file_changes'][0]['snippets'][0]['after'], 'x=1')
        self.assertEqual(event['parent_event_id'], '')

    def test_failed_result_and_unknown_outcome(self):
        failed = normalize({'hook_event_name': 'PostToolUse', 'tool_response': {'exit_code': 1}})
        self.assertEqual(failed['status'], 'failed')
        unknown = normalize({'hook_event_name': 'PostToolUse', 'tool_response': 'some output'})
        self.assertEqual(unknown['status'], '')

    def test_shell_command_does_not_invent_diff(self):
        event = normalize({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                           'tool_input': {'command': "sed -i s/old/new/ app.py"}})
        self.assertEqual(event['file_changes'], [])

    def test_messages_and_raw_evidence(self):
        raw = {'hook_event_name': 'UserPromptSubmit', 'prompt': 'hello ✓'}
        self.assertEqual(normalize(raw)['message'], 'hello ✓')
        self.assertEqual(normalize(raw)['raw_event'], raw)
        self.assertEqual(normalize({'hook_event_name': 'Stop', 'last_assistant_message': None})['message'], '')

    def test_edit_and_write_preserve_snippets(self):
        event = normalize({'hook_event_name': 'PreToolUse', 'tool_name': 'Edit',
                           'tool_input': {'file_path': 'x.py', 'old_string': 'x=1', 'new_string': 'x=2'}})
        self.assertEqual(event['file_changes'][0]['snippets'][0]['before'], 'x=1')
        event = normalize({'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
                           'tool_input': {'file_path': 'x.py', 'content': 'x=3'}})
        self.assertEqual(event['file_changes'][0]['snippets'][0]['after'], 'x=3')


if __name__ == '__main__':
    unittest.main()
