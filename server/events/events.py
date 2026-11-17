"""Normalize observed hook data without inventing missing facts."""
from datetime import datetime, timezone
from uuid import uuid4
import re
from difflib import SequenceMatcher
from pathlib import Path
from collections import OrderedDict
import time
import json

from events.action_types import action_type_for_item, normalize_action_type


class FileSnapshots:
    """Observe local files around paired tool events; never infer missing snapshots."""
    def __init__(self):
        self.pending = OrderedDict()

    @staticmethod
    def read(path):
        try:
            with path.open('rb') as stream:
                data = stream.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024 or b'\0' in data:
                return None
            return data.decode('utf-8')
        except FileNotFoundError:
            return ''
        except (OSError, UnicodeError, ValueError):
            return None

    def enrich(self, record):
        now = time.monotonic()
        while self.pending and (len(self.pending) > 64 or next(iter(self.pending.values()))[0] < now - 300):
            self.pending.popitem(last=False)
        key = (record['session_id'], record['turn_id'], record['tool_call_id'])
        if not key[2]:
            return
        if record['hook_event'] == 'PreToolUse':
            snapshots = {}
            for change in record['file_changes']:
                if not change['path']:
                    continue
                path = Path(record['cwd']) / change['path']
                snapshots[change['path']] = self.read(path)
            if snapshots:
                self.pending[key] = (now, snapshots)
        elif record['hook_event'] == 'PostToolUse':
            saved = self.pending.pop(key, None)
            if saved is None:
                return
            for change in record['file_changes']:
                before = saved[1].get(change['path'])
                after = self.read(Path(record['cwd']) / (change['move_to'] or change['path']))
                if before is None or after is None:
                    continue
                lines = []
                old, new = before.splitlines(), after.splitlines()
                for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
                    if tag == 'equal':
                        continue
                    for kind, content, start in (('removed', old[a:b], a), ('added', new[c:d], c)):
                        for number, text in enumerate(content, start + 1):
                            lines.append({'type': kind, 'text': text,
                                          'old_line': number if kind == 'removed' else None,
                                          'new_line': number if kind == 'added' else None})
                change['line_changes'] = lines
                change['line_changes_source'] = 'filesystem_snapshots'
                change['content_changed'] = before != after


def replacement_lines(before, after, full_content=False):
    old, new = before.splitlines(), after.splitlines()
    result = []
    for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for kind, lines, start in (("removed", old[a:b], a), ("added", new[c:d], c)):
            for offset, text in enumerate(lines, start + 1):
                result.append({"type": kind, "text": text,
                               "old_line": None,
                               "new_line": offset if full_content and kind == "added" else None,
                               "hunk_index": 0, "hunk_line": offset})
    return result


def patch_changes(patch):
    """Extract code from apply_patch hunks; these are patch excerpts, not full files."""
    changes = []
    current = None
    hunk = None
    old_line = None
    new_line = None

    def finish_hunk():
        nonlocal hunk
        if hunk is not None:
            current["snippets"].append({
                "location": hunk["location"],
                "before": "\n".join(hunk["before"]),
                "after": "\n".join(hunk["after"]),
            })
            hunk = None

    def finish_file():
        if current is not None:
            finish_hunk()
            current["diff"] = "\n".join(current.pop("lines"))
            changes.append(current)

    for line in patch.splitlines():
        headers = {"*** Update File: ": "update", "*** Add File: ": "add", "*** Delete File: ": "delete"}
        header = next((prefix for prefix in headers if line.startswith(prefix)), None)
        if header:
            finish_file()
            current = {"path": line[len(header):], "operation": headers[header],
                       "move_to": "", "snippet_source": "tool_input_patch",
                       "snippets": [], "line_changes": [], "lines": [line]}
            old_line = None
            new_line = 1 if headers[header] == "add" else None
            continue
        if current is None or line in ("*** Begin Patch", "*** End Patch"):
            continue
        current["lines"].append(line)
        if line.startswith("*** Move to: "):
            current["move_to"] = line[len("*** Move to: "):]
        elif line.startswith("@@"):
            finish_hunk()
            hunk = {"location": line, "before": [], "after": []}
            positions = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            old_line = int(positions[1]) if positions else None
            new_line = int(positions[2]) if positions else None
        elif line and line[0] in " +-" and not line.startswith("***"):
            if hunk is None:
                hunk = {"location": "", "before": [], "after": []}
            if line[0] in "-+":
                current["line_changes"].append({
                    "type": "removed" if line[0] == "-" else "added",
                    "text": line[1:],
                    "old_line": old_line if line[0] == "-" else None,
                    "new_line": new_line if line[0] == "+" else None,
                    "hunk_index": len(current["snippets"]),
                    "hunk_line": len(hunk["before"] if line[0] == "-" else hunk["after"]) + 1,
                })
            if line[0] in " -":
                hunk["before"].append(line[1:])
                if old_line is not None:
                    old_line += 1
            if line[0] in " +":
                hunk["after"].append(line[1:])
                if new_line is not None:
                    new_line += 1
    finish_file()
    return changes


def file_changes(tool, inputs):
    if isinstance(inputs, str) and "*** Begin Patch" in inputs:
        return patch_changes(inputs)
    if not isinstance(inputs, dict):
        return []
    for key in ("patch", "command", "input"):
        patch = inputs.get(key)
        if isinstance(patch, str) and patch.lstrip().startswith("*** Begin Patch"):
            return patch_changes(patch)
    path = inputs.get("file_path", inputs.get("path", ""))
    if tool.lower() == "edit" and isinstance(inputs.get("old_string"), str) and isinstance(inputs.get("new_string"), str):
        return [{"path": path, "operation": "update", "move_to": "", "diff": "",
                 "line_changes": replacement_lines(inputs["old_string"], inputs["new_string"]),
                 "snippet_source": "tool_input_replacement", "snippets": [{
                     "location": "", "before": inputs["old_string"], "after": inputs["new_string"]}]}]
    if tool.lower() == "write" and isinstance(inputs.get("content"), str):
        return [{"path": path, "operation": "write", "move_to": "", "diff": "",
                 "line_changes": replacement_lines("", inputs["content"], full_content=True),
                 "snippet_source": "tool_input_content", "snippets": [{
                     "location": "", "before": "", "after": inputs["content"]}]}]
    return []


def outcome(response):
    if isinstance(response, dict):
        for field in ("isError", "is_error"):
            if isinstance(response.get(field), bool):
                return "failed" if response[field] else "succeeded"
        code = response.get("exit_code")
        if isinstance(code, int) and not isinstance(code, bool):
            return "succeeded" if code == 0 else "failed"
    return ""


def message_id(event):
    if event.get('message_id'):
        return event['message_id']
    if event.get('hook_event_name') not in ('UserPromptSubmit', 'Stop'):
        return ''
    path, turn = event.get('transcript_path'), event.get('turn_id')
    if not path or not turn:
        return ''
    expected = 'UserMessage' if event['hook_event_name'] == 'UserPromptSubmit' else 'AgentMessage'
    try:
        with open(path, encoding='utf-8') as stream:
            found = ''
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                payload = record.get('payload', {})
                item = payload.get('item', {})
                if (payload.get('turn_id') == turn and item.get('type') == expected
                        and (expected == 'UserMessage' or item.get('phase') == 'final_answer')):
                    found = item.get('id', '')
            return found
    except OSError:
        return ''


def normalize(event):
    name = event.get("hook_event_name", "")
    types = {"UserPromptSubmit": "user_message", "Stop": "assistant_message",
             "PreToolUse": "tool_call", "PostToolUse": "tool_result",
             "SessionStart": "session_start", "SessionEnd": "session_end", "Interrupt": "interrupt"}
    inputs = event.get("tool_input", "")
    tool = event.get("tool_name", "")
    supplied_type = event.get('action_type', '')
    action_type = normalize_action_type(supplied_type) if supplied_type else ''
    if not action_type and event.get('tool_use_id') and event.get('transcript_path'):
        # Codex records the native item type alongside the hook's tool ID.
        try:
            with open(event['transcript_path'], encoding='utf-8') as stream:
                for line in stream:
                    try:
                        payload = json.loads(line).get('payload', {})
                    except ValueError:
                        continue
                    item = payload.get('item', {})
                    if (payload.get('turn_id') == event.get('turn_id')
                            and item.get('id') == event['tool_use_id']):
                        action_type = action_type_for_item(item)
        except OSError:
            pass
    response = event.get("tool_response", "")
    message = event.get("prompt", "") if name == "UserPromptSubmit" else event.get("last_assistant_message", "") if name == "Stop" else ""
    return {
        "schema_version": "1.0",
        "event_id": str(uuid4()),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "occurred_at": "",
        "session_id": event.get("session_id") or "",
        "turn_id": event.get("turn_id") or "",
        "message_id": message_id(event),
        "tool_call_id": event.get("tool_use_id") or "",
        "parent_event_id": "",
        "event_type": types.get(name, ""),
        "hook_event": name,
        "model": event.get("model") or "",
        "cwd": event.get("cwd") or "",
        "message": message or "",
        "tool_name": tool,
        "action_type": action_type,
        "tool_input": inputs,
        "tool_output": response,
        "status": outcome(response) if name == "PostToolUse" else "",
        "change_stage": "requested" if name == "PreToolUse" else "reported" if name == "PostToolUse" else "",
        "file_changes": file_changes(tool, inputs) if name in ("PreToolUse", "PostToolUse") else [],
        "summary": "",
        "raw_event": event,
    }
