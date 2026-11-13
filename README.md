# Codex conversation logger and live DAG

Python 3.9+ only; no dependencies or OpenAI API key required.

- `server/server.py`: HTTP receiver, JSON terminal output, and live graph UI.
- `codex/`: local Codex plugin that sends lifecycle hook events.

## 1. Start the receiver

In a terminal on the same machine where Codex executes hooks:

```bash
cd /home/x/codex_ent
python3 server/server.py
```

Leave it running. It listens on `http://127.0.0.1:8765/events`.
Open `http://127.0.0.1:8765/` to watch the graph build live. JSON still prints to
the terminal. The server is loopback only by default and has no authentication.

## Live conversation DAG

The same server serves the UI at `/`, a snapshot at `/api/graph`, and live
Server-Sent Events at `/api/stream`. No frontend build or external libraries are
required. Select a session, click a node to inspect its evidence and exact line
changes, and use Follow live to scroll to incoming nodes.

The three node types are PERSON, AI ACTION, and AI FINAL RESPONSE. Each changed
file creates its own action, even when one tool call changes multiple files.
Calls without file changes create a tool action. Post-tool events update existing
actions rather than adding duplicates. Each turn uses three depth layers
(0/1/2, then 3/4/5, etc.); all actions within a turn share a layer. The prompt
branches to its actions and they merge into the final response. The final response
connects to the next prompt. Turns without tools connect prompt directly to final.
Sessions remain separate. Incomplete turns show only the events received so far.

Incoming normalized events are now saved in `server/graph.sqlite3` and replayed
on restart. History starts when this updated receiver runs; older terminal output
is not imported automatically. Use `--database /path/to/history.sqlite3` for another
database or `--database :memory:` to disable persistence. Store the database locally;
it contains the prompts, tool inputs, and results sent to the logger.

## 2. Test the sender before installing

In another terminal:

```bash
cd /home/x/codex_ent
printf '%s\n' '{"hook_event_name":"UserPromptSubmit","session_id":"smoke-test","prompt":"Hello from Codex"}' | python3 codex/hooks/send_event.py
```

The sender prints `{}` (the hook protocol response). The server terminal prints
a JSON record with `event_type: "user_message"` and `message: "Hello from Codex"`. Check server health with:

```bash
curl http://127.0.0.1:8765/health
```

## 3. Register and install the plugin

Run this yourself in your terminal; it adds/updates only the `codex` entry in
the project's `.agents/plugins/marketplace.json`, preserving other entries:

```bash
cd /home/x/codex_ent
python3 codex/register.py
```

Restart Codex and open this project. Open the Plugins directory, choose the
**Codex Local** source (or the existing marketplace name if you already had
one), and install/enable **codex**. Review and trust its hook commands when
Codex requests it; installation alone does not trust hooks. Start a new chat
in this project after installation.

If the app lists the plugin but the runtime discovers no hooks, register the
catalog with the runtime as well:

```bash
/usr/lib/chatgpt/resources/codex plugin marketplace add /home/x/codex_ent
/usr/lib/chatgpt/resources/codex plugin add codex@codex-local
```

This package uses `.codex-plugin/plugin.json` as its active manifest. On the
tested desktop build (0.163.0-alpha.10.2), adding a root `plugin.json` caused
the runtime to miss the hook declarations. `plugin.portable.json` is an inactive
reference example, not an active manifest.

## 4. Test a real conversation

Keep the receiver running and send this in that new Codex chat:

> Run `pwd` in the terminal, then reply with “Logger test complete.”

The receiver prints one JSON object per line. You should receive `user_message`,
`tool_call`, `tool_result`, and `assistant_message` events. Each object includes
session/turn IDs, a receiver-generated event ID, the receive timestamp, tool
inputs/outputs, and the original hook JSON in `raw_event`.

Unknown scalar fields use `""`; unknown collections use `[]`. Missing timestamps,
parent links, summaries, and execution outcomes are not inferred. `tool_call_id`
contains the runtime's `tool_use_id` when supplied, so calls and results can be
linked without guessing. `received_at` is the receiver time, not the action time.

For apply_patch inputs, `file_changes` includes each path, operation, per-file
`diff`, and `snippets` with `before`, `after`, and the patch's hunk `location`.
Edit replacements and Write content are also captured when supplied by those
tools. Excerpts come from tool inputs, not a filesystem snapshot. A pre-tool event
has `change_stage: "requested"`; a post-tool event has `"reported"`. An outcome is
populated only for explicit `exit_code` or `isError`/`is_error` fields. A proposed
patch is not proof it applied. Empty code may mean an empty snippet or unavailable
content; `snippet_source` identifies the recorded evidence.

Shell/script changes do not yet get automatic before/after snapshots. Their raw
commands and output are retained, but missing code changes stay blank. Deletion
patches that only name a file have no deleted-code snippet.

Restart the Python server after updating receiver code. No plugin reinstall is
needed for this JSON formatting change.

Each file change also includes `line_changes`: one entry per added or removed
line, with `type`, exact `text` (including indentation and empty lines),
`old_line`, `new_line`, zero-based `hunk_index`, and one-based `hunk_line`.
File line numbers are populated when the patch supplies numeric hunk positions,
or for added files and Write content starting at line 1. Unknown or inapplicable
file positions are `null`; unnumbered apply_patch hunks and Edit replacements
provide positions within their excerpts instead. Write content describes the new
file only; it cannot report removed lines without the previous contents.

The receiver now snapshots local UTF-8 text files around paired PreToolUse and
PostToolUse events. On the post-tool record, `line_changes_source` is
`filesystem_snapshots` when both reads are available, and `line_changes` contains
actual one-based old/new file line numbers. `content_changed` records whether
the contents differ. These are observed changes during the tool interval;
concurrent edits may also appear. Pre-tool entries still describe the requested
patch. Missing pairs, unreadable/binary files, and files larger than 1 MiB retain
the patch-based fallback. Snapshots are in memory and expire after five minutes;
restart the receiver to activate this feature.

Session start/end and interruption events are also forwarded as JSON. Session
end does not necessarily fire immediately when you switch away from a chat.

## Scope and troubleshooting

- This observes supported hook events: prompts, tool calls/results, and the
  latest assistant message at the end of a turn. It does not stream individual
  words, capture every intermediate commentary message, or expose private reasoning.
- The server receives the complete hook JSON; its display selects the relevant
  fields. Prompts and tool results can include sensitive content.
- Delivery is best effort, with a one-second HTTP timeout and no retry/storage.
  A stopped receiver produces a sender diagnostic but does not block the chat.
- If the manual sender works but the chat stays silent, confirm the plugin is
  enabled, its hooks are trusted, and Python 3 is on Codex's PATH. Hook plugins
  are for manual installation in Codex desktop; host/version support may vary.
- The hook process and receiver must share a machine/network namespace. A
  remote/cloud Codex runtime cannot reach your laptop through `127.0.0.1`.
- To use another local port, start the server with `--port 8766` and launch
  Codex with `CODEX_SERVER_URL=http://127.0.0.1:8766/events` in its environment.
- Codex installs a cached copy of local plugins. After editing `codex`, reinstall
  or refresh the plugin and review any changed hooks before starting a new chat.
- Disable/uninstall **codex** in Plugins to stop forwarding; Ctrl+C stops the server.

Official references: [plugin packaging and local marketplaces](https://developers.openai.com/plugins/build/plugins)
and [hooks, supported events, and trust review](https://learn.chatgpt.com/docs/hooks).
