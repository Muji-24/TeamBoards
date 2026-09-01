from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration
from langchain_core.outputs import ChatResult

from djangoproject.boards.llm import parse_proposed_tasks
from djangoproject.boards.llm import run_board_chat_stream
from djangoproject.boards.models import Task
from djangoproject.boards.schemas import ProposedTaskList
from djangoproject.boards.schemas import TaskDraft
from djangoproject.boards.tests.factories import ProjectFactory
from djangoproject.boards.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


class FakeBoardLLM(BaseChatModel):
    """Minimal chat model so LangGraph (or the bind_tools fallback) can run tools."""

    def bind_tools(self, tools, **kwargs):
        return self
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-board"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1] if messages else None
        if isinstance(last, ToolMessage):
            message = AIMessage(content="Added **From agent** as `#1`.")
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_task",
                        "args": {"title": "From agent", "status": "todo"},
                        "id": "call_1",
                        "type": "tool_call",
                    },
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def stream(self, messages, **kwargs):
        result = self._generate(messages)
        yield result.generations[0].message


@patch("djangoproject.boards.llm.build_chat_model")
@pytest.mark.django_db(transaction=True)
def test_stream_runs_create_task_tool(mock_build, user):
    mock_build.return_value = FakeBoardLLM()
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)

    events = list(
        run_board_chat_stream(
            user=user,
            user_message="add From agent",
            history=[],
            project_brief="(test)",
            project_id=project.pk,
        ),
    )

    assert Task.objects.filter(project=project, title="From agent").exists()
    kinds = [event["type"] for event in events]
    assert "tool" in kinds
    assert kinds[-1] == "done"
    assert events[-1]["reply"]["board_changed"] is True
    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["label"]


@patch("djangoproject.boards.llm.build_chat_model")
def test_parse_proposed_tasks_uses_structured_output(mock_build):
    structured = MagicMock()
    structured.invoke.return_value = ProposedTaskList(
        tasks=[TaskDraft(title="Write docs", status="todo")],
    )
    mock_build.return_value.with_structured_output.return_value = structured

    result = parse_proposed_tasks("please add write docs")

    mock_build.return_value.with_structured_output.assert_called_once_with(
        ProposedTaskList,
    )
    assert result.tasks[0].title == "Write docs"
    structured.invoke.assert_called_once()
