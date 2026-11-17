"""Explicit mappings from Codex protocol items to ConversationMemoryTree types."""

# ThreadItem variants from `codex app-server generate-ts --experimental`.
# Sleep and image generation are known tool variants represented by the library's
# dynamic-tool category; it has no dedicated sleep/image-generation categories.
ITEM_ACTION_TYPES = {
    'userMessage': 'human_input',
    'hookPrompt': 'human_input',
    'functionCallOutput': 'tool_result',
    'plan': 'assistant_plan',
    'reasoning': 'reasoning_summary',
    'commandExecution': 'command_execution',
    'fileChange': 'file_change',
    'mcpToolCall': 'mcp_tool_call',
    'dynamicToolCall': 'dynamic_tool_call',
    'collabAgentToolCall': 'agent_collaboration',
    'subAgentActivity': 'agent_collaboration',
    'imageView': 'image_view',
    'sleep': 'dynamic_tool_call',
    'imageGeneration': 'dynamic_tool_call',
    'enteredReviewMode': 'review_started',
    'exitedReviewMode': 'review_completed',
    'contextCompaction': 'context_compaction',
}
AGENT_PHASE_TYPES = {
    None: 'assistant_partial_response',
    'commentary': 'assistant_commentary',
    'final_answer': 'assistant_response',
}
WEB_ACTION_TYPES = {
    'search': 'web_search',
    'open_page': 'web_open',
    'openPage': 'web_open',
    'find_in_page': 'web_find',
    'findInPage': 'web_find',
    'other': 'web_search',
}
EXTENSION_ACTION_TYPES = {
    'web.search': 'web_search',
    'web.open': 'web_open',
    'web.find': 'web_find',
}
# Canonical library types may also be supplied directly by the event producer.
LIBRARY_ACTION_TYPES = frozenset({
    'human_input', 'assistant_response', 'assistant_commentary',
    'assistant_partial_response', 'assistant_plan', 'reasoning_summary',
    'web_search', 'web_open', 'web_find', 'command_execution', 'file_change',
    'image_view', 'mcp_tool_call', 'dynamic_tool_call', 'tool_result',
    'agent_collaboration', 'user_input_request', 'approval_request',
    'approval_response', 'mcp_elicitation', 'review_started', 'review_completed',
    'context_compaction',
})


def action_type_for_item(item):
    """Translate a defined Codex item, rejecting names outside the explicit map."""
    native = item.get('type', '')
    # Transcript item names start with capitals; app-server names start lowercase.
    kind = native[:1].lower() + native[1:]
    try:
        if kind == 'agentMessage':
            return AGENT_PHASE_TYPES[item.get('phase')]
        if kind == 'webSearch':
            action = item.get('action')
            # A WebSearch item without an action is the protocol's search request.
            if action is None:
                return 'web_search'
            return WEB_ACTION_TYPES[action['type']]
        if kind == 'extension':
            return EXTENSION_ACTION_TYPES[item['kind']]
        return ITEM_ACTION_TYPES[kind]
    except KeyError as error:
        raise ValueError(f'Unrecognized Codex item type or variant: {item!r}') from error


def normalize_action_type(value):
    """Accept a canonical library type or an explicitly mapped Codex name."""
    if value in LIBRARY_ACTION_TYPES:
        return value
    if value in EXTENSION_ACTION_TYPES:
        return EXTENSION_ACTION_TYPES[value]
    return action_type_for_item({'type': value})
