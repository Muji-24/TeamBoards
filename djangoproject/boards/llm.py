"""LangGraph ReAct agent over Django-backed tools.

Gemini is the model. LangChain/LangGraph is the glue: prompts, tools,
structured schemas, streaming. The agent graph decides when to call tools;
Django still checks membership on every write.

This is not a hardcoded board dump and not a fixed 5-round loop.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from djangoproject.boards.schemas import BoardReply
from djangoproject.boards.schemas import ProposedTaskList
from djangoproject.boards.schemas import WorkPlan
from djangoproject.boards.tools import build_board_tools

if TYPE_CHECKING:
    from collections.abc import Iterator

    from langgraph.graph.state import CompiledStateGraph

TOOL_LABELS = {
    "get_board_summary": "Reading the board",
    "search_tasks": "Searching cards",
    "list_tasks": "Listing cards",
    "get_task": "Opening a card",
    "list_members": "Checking members",
    "plan_work": "Planning work",
    "create_task": "Creating a card",
    "create_tasks_from_notes": "Adding cards from notes",
    "update_task_status": "Moving a card",
    "assign_task": "Assigning a card",
    "set_due_date": "Setting a due date",
    "set_priority": "Setting priority",
    "add_comment": "Adding a comment",
    "apply_label": "Applying a label",
}


def _system_prompt(project_brief: str) -> str:
    return (
        "You are TeamBoards' assistant — a capable copilot for a kanban board.\n"
        f"{project_brief}\n\n"
        "How you work:\n"
        "- Inspect live state with tools before talking about specific cards. "
        "Never invent task ids.\n"
        "- Prefer get_board_summary or search_tasks over listing everything.\n"
        "- Use plan_work to break a goal into cards. Set create=true only when "
        "the user asked you to add them.\n"
        "- After writes, recap what changed.\n\n"
        "How you write (GitHub-flavored markdown):\n"
        "- Short headings, bullets, and numbered lists.\n"
        "- **Bold** card titles. Refer to cards as `#12`.\n"
        "- A compact markdown table only when comparing several cards.\n"
        "- No filler like 'Sure!' or 'As an AI'."
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
    """Force Gemini to fill ProposedTaskList instead of a paragraph."""
    llm = build_chat_model().with_structured_output(ProposedTaskList)
    result = llm.invoke(
        "Extract task cards from these notes. "
        "Default status is todo if unspecified.\n\n"
        f"{notes}",
    )
    if isinstance(result, ProposedTaskList):
        return result
    return ProposedTaskList.model_validate(result)


def draft_work_plan(goal: str, board_snapshot: str) -> WorkPlan:
    """Nested structured-output chain: a goal becomes typed TaskDrafts."""
    llm = build_chat_model().with_structured_output(WorkPlan)
    result = llm.invoke(
        "Break this goal into board cards. Keep titles short. "
        "Respect work already on the board (do not duplicate).\n\n"
        f"Goal:\n{goal}\n\nCurrent board:\n{board_snapshot}",
    )
    if isinstance(result, WorkPlan):
        return result
    return WorkPlan.model_validate(result)


def history_to_messages(history: list[dict]) -> list[BaseMessage]:
    """Turn JSON [{role, content}] into LangChain message objects."""
    messages: list[BaseMessage] = []
    for item in history[-24:]:
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


def build_board_agent(
    *,
    model: Any,
    tools: list,
    project_brief: str,
) -> CompiledStateGraph:
    return create_agent(
        model,
        tools,
        system_prompt=_system_prompt(project_brief),
        name="board_agent",
    )


def _tool_event(name: str, result: str) -> dict:
    label = TOOL_LABELS.get(name, name.replace("_", " "))
    return {"type": "tool", "name": name, "label": label, "result": result}


def _token_events(data: Any) -> Iterator[dict]:
    chunk = data[0] if isinstance(data, tuple) else data
    meta = data[1] if isinstance(data, tuple) and len(data) > 1 else {}
    if (meta or {}).get("langgraph_node") == "tools":
        return
    text = _content_to_text(getattr(chunk, "content", None))
    if text:
        yield {"type": "token", "text": text}


def _tool_update_events(data: dict) -> Iterator[dict]:
    for node, update in data.items():
        if node != "tools" or not isinstance(update, dict):
            continue
        yield {"type": "status", "text": "Updating the board…"}
        for msg in update.get("messages") or []:
            if isinstance(msg, ToolMessage):
                name = getattr(msg, "name", "") or ""
                result = str(getattr(msg, "content", "") or "")
                yield _tool_event(name, result)


def _stream_graph(
    graph: CompiledStateGraph,
    messages: list[BaseMessage],
) -> Iterator[dict]:
    """Yield SSE events from LangGraph message/update streams."""
    spoken = ""
    for item in graph.stream(
        {"messages": messages},
        stream_mode=["messages", "updates"],
        config={"recursion_limit": 15},
    ):
        if not isinstance(item, tuple) or len(item) != 2:  # noqa: PLR2004
            continue
        mode, data = item
        if mode == "messages":
            for event in _token_events(data):
                spoken += str(event["text"])
                yield event
        elif mode == "updates" and isinstance(data, dict):
            yield from _tool_update_events(data)
    if spoken.strip():
        yield {"type": "_spoken", "text": spoken.strip()}


def _stream_bind_tools_fallback(
    *,
    model: Any,
    tools: list,
    messages: list[BaseMessage],
) -> Iterator[dict]:
    """Used in tests (and as a safety net) when the object is not a real chat model."""
    llm_with_tools = model.bind_tools(tools)
    tool_map = {tool.name: tool for tool in tools}
    spoken = ""
    for _ in range(8):
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
                except (TypeError, ValueError) as exc:
                    result = f"Tool {name} failed: {exc}"
            yield _tool_event(name, result)
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=str(call.get("id") or name),
                    name=name,
                ),
            )
    if spoken.strip():
        yield {"type": "_spoken", "text": spoken.strip()}


def run_board_chat_stream(
    *,
    user,
    user_message: str,
    history: list[dict],
    project_brief: str,
    project_id: int | None,
) -> Iterator[dict]:
    """Yield SSE-ready dicts: token, tool, then a structured done event."""
    tools, tool_state = build_board_tools(user=user, project_id=project_id)
    model = build_chat_model()
    messages: list[BaseMessage] = [
        *history_to_messages(history),
        HumanMessage(content=user_message),
    ]

    spoken = ""
    try:
        graph = build_board_agent(
            model=model,
            tools=tools,
            project_brief=project_brief,
        )
        events = _stream_graph(graph, messages)
    except (TypeError, ValueError, AttributeError):
        events = _stream_bind_tools_fallback(
            model=model,
            tools=tools,
            messages=messages,
        )

    for event in events:
        if event["type"] == "_spoken":
            spoken = str(event["text"])
            continue
        yield event

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
    project_brief: str,
    project_id: int | None,
) -> str:
    """Collect a stream into one string (tests / non-streaming callers)."""
    message = ""
    for event in run_board_chat_stream(
        user=user,
        user_message=user_message,
        history=history,
        project_brief=project_brief,
        project_id=project_id,
    ):
        if event["type"] == "token":
            message += str(event["text"])
        elif event["type"] == "done":
            message = str(event["reply"]["message"])
    return message
