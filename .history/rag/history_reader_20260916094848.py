from typing import Any


def history_reader(context: dict[str, Any] | None) -> dict[str, Any]:
    """
    Extract conversation history information from the Context Object.

    Args:
        context: Context Object containing recent_messages and
            conversation_summary.

    Returns:
        A dictionary containing:
        - recent_messages: list of recent messages
        - conversation_summary: conversation summary string
    """
if not isinstance(context, dict):
    return {
        "recent_messages": [],
        "conversation_summary": "",
    }

    recent_messages = context.get("recent_messages", [])
    conversation_summary = context.get("conversation_summary", "")

    if not isinstance(recent_messages, list):
        recent_messages = []

    if isinstance(conversation_summary, str):
        summary = conversation_summary
    elif isinstance(conversation_summary, dict):
        summary = conversation_summary.get("summary", "")
        if not isinstance(summary, str):
            summary = ""
    else:
        summary = ""

    return {
        "recent_messages": recent_messages,
        "conversation_summary": summary,
    }