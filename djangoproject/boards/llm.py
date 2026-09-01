"""LangChain lesson lives here — Django only *calls* this.

LangChain is not the model. Gemini is the model.
LangChain is the glue: prompts, tools, structured schemas, streaming.

What this module does now:

1. Tools — bind Python functions onto Gemini. The model may call
   list_tasks / create_task / update_task_status. Django still checks membership.

2. Streaming — llm.stream() yields tokens. The view forwards them as SSE.

3. Structured output — Pydantic schemas on tools, plus
   with_structured_output(ProposedTaskList) when extracting a pasted list.
   BoardReply is the typed final SSE event.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import ValidationError

from djangoproject.boards.schemas import BoardReply
from djangoproject.boards.schemas import ProposedTaskList
from djangoproject.boards.tools import build_board_tools

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = (
    "You are a concise assistant for a team task board. "
    "Use tools to list, create, move, assign, label, comment on, or schedule tasks. "
    "list_tasks shows live cards. create_task adds one card. "
    "create_tasks_from_notes extracts several cards from a pasted list. "
    "update_task_status moves a card; use the numeric id from list_tasks. "
    "assign_task uses a member email. set_due_date uses YYYY-MM-DD. "
    "set_priority is low/medium/high/urgent. apply_label uses an existing label name. "
    "If there is no project, say they should open a board. "
    "Keep answers short.\n\n"
    "Board snapshot:\n{board_context}"
)


class ChatNotConfigured(RuntimeError):
    """Raised when GOOGLE_API_KEY is missing so the view can return 503."""


def _require_api_key() -> str:
    key = getattr(settings, "GOOGLE_API_KEY", "") or ""
    if not key:
        msg = (
            "GOOGLE_API_KEY is not set. Add it to .envs/.local/.django "
            "and restart the django container."
        )
        raise ChatNotConfigured(msg)
    return key


def build_chat_model() -> ChatGoogleGenerativeAI:
    """Vendor wrapper. Swap this class to change providers."""
    return ChatGoogleGenerativeAI(
        model=getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash"),
        temperature=0.2,
        google_api_key=_require_api_key(),
        thinking_config={"thinking_budget": 0},
    )


def parse_proposed_tasks(notes: str) -> ProposedTaskList:
    """Force Gemini to fill ProposedTaskList instead of a paragraph.

    with_structured_output sends the Pydantic schema to the model and
    returns an instance — not a string you have to regex.
    """
    llm = build_chat_model().with_structured_output(ProposedTaskList)
    result = llm.invoke(
        "Extract task cards from these notes. "
        "Default status is todo if unspecified.\n\n"
        f"{notes}",
    )
    if isinstance(result, ProposedTaskList):
        return result
    return ProposedTaskList.model_validate(result)


def history_to_messages(history: list[dict]) -> list[BaseMessage]:
    """Turn JSON [{role, content}] into LangChain message objects."""
    messages: list[BaseMessage] = []
    for item in history[-20:]:
        role = item.get("role")
        content = item.get("content", "")
        if role == "human":
            messages.append(HumanMessage(content=content))
        elif role == "ai":
            messages.append(AIMessage(content=content))
    return messages


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", "") or "")
        return "".join(parts)
    return str(content)


def _as_tool_call(call: Any) -> dict:
    if isinstance(call, dict):
        return call
    return {
        "name": getattr(call, "name", "") or "",
        "args": getattr(call, "args", None) or {},
        "id": getattr(call, "id", "") or "",
    }


def _tool_args(call: dict) -> dict:
    args = call.get("args") or {}
    if isinstance(args, str):
        return json.loads(args) if args else {}
    return args


def run_board_chat_stream(
    *,
    user,
    user_message: str,
    history: list[dict],
    board_context: str,
    project_id: int | None,
) -> Iterator[dict]:
    """Yield SSE-ready dicts: token, tool, then a structured done event."""
    tools, tool_state = build_board_tools(user=user, project_id=project_id)
    llm_with_tools = build_chat_model().bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [
        SystemMessage(
            content=SYSTEM_PROMPT.format(
                board_context=board_context or "(no project loaded)",
            ),
        ),
        *history_to_messages(history),
        HumanMessage(content=user_message),
    ]

    spoken = ""
    for _ in range(MAX_TOOL_ROUNDS):
        assembled: AIMessage | None = None
        for chunk in llm_with_tools.stream(messages):
            assembled = chunk if assembled is None else assembled + chunk
            text = _content_to_text(getattr(chunk, "content", None))
            if text:
                spoken += text
                yield {"type": "token", "text": text}

        if assembled is None:
            break

        tool_calls = getattr(assembled, "tool_calls", None) or []
        if not tool_calls:
            messages.append(assembled)
            break

        spoken = ""
        messages.append(assembled)
        yield {"type": "status", "text": "Updating the board…"}
        for raw_call in tool_calls:
            call = _as_tool_call(raw_call)
            name = call.get("name") or ""
            tool = tool_map.get(name)
            if tool is None:
                result = f"Unknown tool: {name}"
            else:
                try:
                    result = str(tool.invoke(_tool_args(call)))
                except (TypeError, ValueError, ValidationError) as exc:
                    result = f"Tool {name} failed: {exc}"
            yield {"type": "tool", "name": name, "result": result}
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=str(call.get("id") or name),
                ),
            )

    if not spoken.strip() and tool_state.actions:
        spoken = "; ".join(tool_state.actions)
        yield {"type": "token", "text": spoken}

    reply = BoardReply(
        message=spoken.strip() or "Done.",
        board_changed=tool_state.board_changed,
        actions=list(tool_state.actions),
    )
    yield {"type": "done", "reply": reply.model_dump()}


def run_board_chat(
    *,
    user,
    user_message: str,
    history: list[dict],
    board_context: str,
    project_id: int | None,
) -> str:
    """Collect a stream into one string (tests / non-streaming callers)."""
    message = ""
    for event in run_board_chat_stream(
        user=user,
        user_message=user_message,
        history=history,
        board_context=board_context,
        project_id=project_id,
    ):
        if event["type"] == "token":
            message += str(event["text"])
        elif event["type"] == "done":
            message = str(event["reply"]["message"])
    return message
