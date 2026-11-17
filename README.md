# Codex conversation logger and live DAG

A local Codex plugin forwards conversation hook events to a Python receiver. The
receiver prints normalized JSON, stores completed interactions through
DotVectorDB's `ConversationMemoryTree`, and serves a live conversation graph.
The plugin manifest version is `0.1.1`.

## Start the receiver

From the project root, in your Python environment:

```bash
python -m pip install -r requirements.txt
python server/server.py
```

Configure the environment required by DotVectorDB's default providers, including
`OPENAI_API_KEY`. The server loads `.env` using `python-dotenv` and uses the
library's default initialization and language model configuration.

Open [the live graph](http://127.0.0.1:8765/) in your browser. Keep the receiver
running while using Codex. It listens on loopback by default and has no
authentication.

| Endpoint | Purpose |
| --- | --- |
| `/` | Live graph UI |
| `/events` | Hook event receiver (POST) |
| `/api/graph` | Graph snapshot (GET) |
| `/api/stream` | Live updates through Server-Sent Events |
| `/health` | Health check |

Optional server arguments:

```bash
python server/server.py --host 127.0.0.1 --port 8766 --database /path/to/memory
```

`--database` selects a dedicated DotVectorDB directory; the default is
`server/ConversationHistory`. For a different port, launch Codex with
`CODEX_SERVER_URL=http://127.0.0.1:8766/events` in its environment.

## Install the Codex plugin

```bash
python3 codex/register.py --install_plugin
```

The installer creates or updates `.agents/plugins/marketplace.json`, preserves
other catalog entries, registers the local marketplace with Codex, and installs
`codex` from that marketplace. The active plugin manifest is
`codex/.codex-plugin/plugin.json`.

The installer finds `codex` on PATH or uses the bundled Linux desktop runtime.
To supply another executable:

```bash
python3 codex/register.py --install_plugin --codex /path/to/codex
```

Restart Codex, review and trust the hook commands when prompted, and start a new
chat. The receiver runs separately. To update only the local marketplace catalog,
run `python3 codex/register.py` without flags.

### Optional NSF OKN MCP server

```bash
python3 codex/register.py --install_nsf_mcp
```

This runs:

```bash
codex mcp add nsf-okn --url https://apps.okn.us/okn-mcp-dev/mcp
```

It also accepts `--codex /path/to/codex`. Run this separately from
`--install_plugin`: when both flags are supplied, only the MCP command runs.

## Verify event delivery

With the receiver running, test the sender from another terminal:

```bash
printf '%s\n' '{"hook_event_name":"UserPromptSubmit","session_id":"smoke-test","prompt":"Hello from Codex"}' | python3 codex/hooks/send_event.py
curl http://127.0.0.1:8765/health
```

The sender prints `{}` for the hook protocol. The receiver prints a JSON record
with `event_type: "user_message"` and `message: "Hello from Codex"`. This minimal
payload checks delivery; graph ingestion requires session, turn, and message or
tool-call identifiers from the runtime.

After installing the plugin, send this in a new Codex chat:

> Run `pwd` in the terminal, then reply with “Logger test complete.”

Expect `user_message`, `tool_call`, `tool_result`, and `assistant_message` events
in the receiver terminal. Select the session in the browser and click a node to
inspect its evidence and file changes. **Follow live** scrolls to incoming nodes;
**Latest turn** jumps to the most recent turn.

## Graph and persistence

Prompts use `human_input`, final responses use `assistant_response`, and tools use
the library's registered action types. Each changed file gets a separate
`file_change` interaction. Calls without file changes use a tool interaction.
Pending tool calls appear in memory; completed results are saved once through
`add_interaction`.

The UI places prompts, actions, and responses in three visual layers per stored
depth. It combines stored edges with display connections derived from ordered
turn IDs: prompt to actions, actions to response, and response to the next prompt.
These extra display connections are not persisted. Sessions remain separate,
and incomplete turns show the events received so far.

`server/knowledge_graph/CodexInteractionGraph.py` subclasses
`ConversationMemoryTree` and uses its public conversation, interaction,
description, and incident-edge methods. Original Codex identifiers remain in the
event data; database keys use the library's `hashing_func.content_hash()`.
Completed interactions persist in the database. Each session's history loads on
first access and is cached; startup does not automatically enumerate all previous
sessions. Pending calls are held only in memory. There is no separate event
journal or replay store.

A background worker summarizes newly saved interactions in order through
`describe_interaction` and the inherited `default_llm_func`. Tool cards show
summaries, while the inspector retains original evidence and structured task
progress. Descriptions persist through the library. Failed summaries leave the
node visible with a summary-unavailable status. Pending calls wait for their
result, and existing undescribed history is not automatically backfilled.

## Event and file-change evidence

Each normalized event includes session/turn identifiers, a receiver-generated
event ID, receive time, tool inputs/outputs, and the original hook JSON in
`raw_event`. `received_at` is receiver time. Missing scalar fields use `""`, and
missing collections use `[]`. Outcomes are populated only from explicit
`exit_code` or `isError`/`is_error` fields.

For supported patch, Edit, and Write inputs, `file_changes` records paths,
operations, diffs, snippets, and per-line additions/removals. Pre-tool records use
`change_stage: "requested"`; post-tool records use `"reported"`. Requested patches
alone do not prove that changes were applied.

For recognized file paths, paired PreToolUse/PostToolUse events also capture
local UTF-8 text snapshots. When both reads are available, the post-tool record
uses `line_changes_source: "filesystem_snapshots"`, includes actual one-based
old/new line numbers, and records `content_changed`. These are observed changes
during the tool interval, so concurrent edits can appear too.

Snapshots are held in memory, expire after five minutes, and skip binary,
unreadable, or larger-than-1-MiB files. Missing snapshots fall back to tool-input
evidence. Shell commands do not automatically provide file paths for snapshots;
their raw inputs and outputs are retained. Unknown or inapplicable line positions
are `null`. Write content cannot identify removed lines without prior contents.

## Scope and troubleshooting

- Supported hooks are `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`,
  `SessionStart`, `SessionEnd`, and `Interrupt`. Session end may not fire as soon
  as you switch chats.
- The logger captures the latest assistant message at the end of a turn. It
  does not stream tokens, capture every intermediate commentary message, or
  expose private reasoning.
- Complete hook payloads are forwarded and may contain sensitive prompts or
  tool results.
- Delivery is best effort with a one-second HTTP timeout and no retry or sender
  storage. A stopped receiver produces a diagnostic without blocking the chat.
- If the manual sender works but chat events are missing, check that the plugin
  is enabled, its hooks are trusted, and Python 3 is on Codex's PATH. Runtime
  support for hooks can vary.
- The hook process must be able to reach the receiver. A remote runtime cannot
  reach a receiver on your laptop through its own `127.0.0.1`.
- After editing plugin files under `codex/`, reinstall or refresh the cached
  plugin and review changed hooks before starting a new chat. Restart the
  Python server after changing receiver code.
- Disable or uninstall **codex** in Plugins to stop forwarding. Ctrl+C stops the
  receiver.

## Development

- `codex/`: plugin manifest, hook declarations, sender, and installation helpers.
- `server/server.py`: server CLI and environment loading.
- `server/events/`: HTTP routes, event normalization, and file snapshots.
- `server/knowledge_graph/`: DotVectorDB integration and graph snapshots.
- `server/front_end/index.html`: graph UI with no frontend build step.

Run the tests in the same Python environment as the receiver:

```bash
PYTHONPATH=server python -m unittest discover -s server/test -p 'test_*.py'
```
