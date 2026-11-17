# Codex conversation logger and live DAG

The receiver uses DotVectorDB's `ConversationMemoryTree` and its dependencies.
Initialization uses the library's default providers and inherited opening flow;
configure the environment required by DotVectorDB (including `OPENAI_API_KEY`).
The HTTP receiver uses `aiohttp`; requests, ingestion, and live streams run on
one asyncio event loop. The hook sender still uses only Python's standard library.

- `server/server.py`: HTTP receiver, JSON terminal output, and live graph UI.
- `codex/`: local Codex plugin that sends lifecycle hook events.

## 1. Start the receiver

From the project root, in your Python environment:

```bash
python -m pip install -r requirements.txt
python server/server.py
```

Leave it running. It listens on `http://127.0.0.1:8765/events`.
Open `http://127.0.0.1:8765/` to watch the graph build live. JSON still prints to
the terminal. The server is loopback only by default and has no authentication.

## Live conversation DAG

The same server serves the UI at `/`, a snapshot at `/api/graph`, and live
Server-Sent Events at `/api/stream`. No frontend build or external libraries are
required. Select a session, click a node to inspect its evidence and exact line
changes, and use Follow live to scroll to incoming nodes.

Nodes use the library's action types: `human_input`, `assistant_response`, and
the registered tool/file action types. Each changed
file creates its own action, even when one tool call changes multiple files.
Calls without file changes create a tool action. Post-tool events update existing
actions rather than adding duplicates. Each turn uses three depth layers
(0/1/2, then 3/4/5, etc.); all actions within a turn share a layer. The prompt
branches to its actions and they merge into the final response. The final response
connects to the next prompt. Turns without tools connect prompt directly to final.
Sessions remain separate. Incomplete turns show only the events received so far.
The UI draws these connections from each session's ordered turn IDs, including
pending actions, and combines them with stored edges without duplicates. These
display connections do not create persistent action records.

Newly saved interactions are summarized in order in a background worker using
`ConversationMemoryTree.describe_interaction` and its inherited `default_llm_func`.
This uses the configured default language model and the library's task extraction,
step-progress, and final-response assessment prompts. Cards display the summary;
the inspector retains the original evidence and includes the structured task
progress details. Summaries are persisted by the library and restored when a chat
loads. Pending tool calls wait for their result before being summarized. A failed
summary leaves its node visible with a summary-unavailable status. Existing
undescribed history is not automatically backfilled.

Persistence uses your `dotvectordb.ConversationMemoryTree.ConversationMemoryTree`
class from the installed PyPI package.

The default database is
`server/ConversationHistory/ConversationHistory.db`. Use `--database /path/to/memory`
to choose a different, dedicated DotVectorDB directory. Nodes are native
`interaction` records and DAG edges are native `action` records. Nodes and UI labels use `action_type` directly;
there is no separate node-type classification.

`CodexInteractionGraph` inherits from `ConversationMemoryTree`. Hook events write
completed interactions using `add_interaction`. Visualization reads existing
edges through the library; this integration does not generate or save edges.
Pending tool actions appear in memory for the UI; the tool result is saved once
when it arrives. Each chat loads once, on first access, through
`get_all_interactions(hash(session_id))`. Edges are read through
`get_incident_edges_of_important_node()` for human-input and answer nodes.
Results are cached separately per conversation, retaining the library's interaction ordering.
Subsequent snapshots use memory; completed writes update that loaded state
without reloading history.
There is no event journal, replay, or duplicate persistent node store. Message
Codex session and interaction IDs are converted to integer database keys using
the inherited `hashing_func.content_hash()`. Original IDs remain in event data. Snapshot depth is the library's
stored `interaction_depth`; the UI spaces the three node types within each round.

`server/knowledge_graph/CodexInteractionGraph.py` defines `CodexInteractionGraph(ConversationMemoryTree)`, which adds
event ingestion and UI snapshots using inherited methods.
It uses `get_conversation()` and `add_conversation()` for each session and the
library's interaction and incident-edge getters and add methods. Loading and visualizing a chat use its stored edges
without reconstructing connections from turn IDs. There are no SQL statements
or direct connection accesses in the integration. Startup uses the inherited
context-manager lifecycle. No library files are edited.

History persists in the conversation-memory directory and reloads on restart.
The frontend and HTTP API are unchanged.

Run the tests in the same environment:

```bash
PYTHONPATH=server python -m unittest discover -s server/test -p 'test_*.py'
```

## 2. Test the sender before installing

From the project root in another terminal:

```bash
printf '%s\n' '{"hook_event_name":"UserPromptSubmit","session_id":"smoke-test","prompt":"Hello from Codex"}' | python3 codex/hooks/send_event.py
```

The sender prints `{}` (the hook protocol response). The server terminal prints
a JSON record with `event_type: "user_message"` and `message: "Hello from Codex"`. Check server health with:

```bash
curl http://127.0.0.1:8765/health
```

## 3. Register and install the plugin

Run one command from the project directory:

```bash
python3 codex/register.py --install_plugin
```

The installer creates the local marketplace catalog (including on a fresh clone),
registers it with Codex, and installs the plugin. Other catalog entries are preserved.
It finds `codex` on PATH or the bundled Linux desktop runtime. For another location:

```bash
python3 codex/register.py --install_plugin --codex /path/to/codex
```

Restart Codex, review and trust the hook commands when prompted, and start a new
chat. Keep the receiver running separately using the command in section 1.
For catalog registration only, `python3 codex/register.py` is still available.

This package uses `.codex-plugin/plugin.json` as its active manifest. On the
tested desktop build (0.163.0-alpha.10.2), adding a root `plugin.json` caused
the runtime to miss the hook declarations.

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
