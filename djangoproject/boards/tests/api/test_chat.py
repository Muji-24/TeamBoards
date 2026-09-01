import json
from http import HTTPStatus
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from djangoproject.boards.models import Task
from djangoproject.boards.schemas import ProposedTaskList
from djangoproject.boards.schemas import TaskDraft
from djangoproject.boards.tests.factories import ProjectFactory
from djangoproject.boards.tests.factories import TaskFactory
from djangoproject.boards.tests.factories import WorkspaceFactory
from djangoproject.boards.tools import build_board_tools
from djangoproject.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def _tool(tools, name: str):
    return next(item for item in tools if item.name == name)


def _sse_events(response) -> list[dict]:
    body = b"".join(response).decode()
    events = []
    for block in body.split("\n\n"):
        line = next(
            (part[6:] for part in block.split("\n") if part.startswith("data: ")),
            "",
        )
        if line:
            events.append(json.loads(line))
    return events


def test_chat_requires_auth(api_client: APIClient):
    response = api_client.post("/api/chat/", {"message": "hi"}, format="json")
    assert response.status_code == HTTPStatus.FORBIDDEN


@patch("djangoproject.boards.api.chat.run_board_chat_stream")
def test_chat_streams_reply(mock_run, user, api_client: APIClient):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    TaskFactory.create(project=project, title="Write docs", created_by=user)
    mock_run.return_value = iter(
        [
            {"type": "token", "text": "Summarized."},
            {
                "type": "done",
                "reply": {
                    "message": "Summarized.",
                    "board_changed": False,
                    "actions": [],
                },
            },
        ],
    )
    api_client.force_authenticate(user)

    response = api_client.post(
        "/api/chat/",
        {
            "message": "What is open?",
            "history": [],
            "project_id": project.pk,
        },
        format="json",
        HTTP_ACCEPT="text/event-stream",
    )

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"].startswith("text/event-stream")
    events = _sse_events(response)
    assert events[0] == {"type": "status", "text": "Working…"}
    assert events[1] == {"type": "token", "text": "Summarized."}
    assert events[-1]["reply"]["message"] == "Summarized."
    kwargs = mock_run.call_args.kwargs
    assert project.name in kwargs["project_brief"]
    assert kwargs["project_id"] == project.pk
    assert "Write docs" not in kwargs["project_brief"]

    stored = api_client.get("/api/chat/", {"project_id": project.pk})
    assert stored.status_code == HTTPStatus.OK
    assert stored.json()["messages"][-1] == {"role": "ai", "content": "Summarized."}


def test_create_task_tool_writes_row(user):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    tools, state = build_board_tools(user=user, project_id=project.pk)

    result = _tool(tools, "create_task").invoke(
        {"title": "Write tests", "status": "todo"},
    )

    task = Task.objects.get(project=project, title="Write tests")
    assert task.status == Task.Status.TODO
    assert task.created_by == user
    assert state.board_changed is True
    assert str(task.pk) in result


def test_list_and_move_task_tools(user):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    task = TaskFactory.create(
        project=project,
        title="Ship it",
        status=Task.Status.TODO,
        created_by=user,
    )
    tools, state = build_board_tools(user=user, project_id=project.pk)

    listed = _tool(tools, "list_tasks").invoke({"status": "todo"})
    assert f"#{task.pk}" in listed
    assert "Ship it" in listed

    moved = _tool(tools, "update_task_status").invoke(
        {"task_id": task.pk, "status": "done"},
    )
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert "done" in moved
    assert state.board_changed is True


def test_tools_reject_outsider(user):
    owner = UserFactory.create()
    workspace = WorkspaceFactory.create(owner=owner)
    project = ProjectFactory.create(workspace=workspace)
    tools, state = build_board_tools(user=user, project_id=project.pk)

    result = _tool(tools, "create_task").invoke({"title": "Nope"})

    assert Task.objects.filter(title="Nope").count() == 0
    assert state.board_changed is False
    assert "belong" in result.lower() or "open a project" in result.lower()


@patch("djangoproject.boards.llm.parse_proposed_tasks")
def test_create_tasks_from_notes_uses_structured_list(mock_parse, user):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    mock_parse.return_value = ProposedTaskList(
        tasks=[
            TaskDraft(title="Alpha", status="todo"),
            TaskDraft(title="Beta", status="doing"),
        ],
    )
    tools, state = build_board_tools(user=user, project_id=project.pk)

    result = _tool(tools, "create_tasks_from_notes").invoke(
        {"notes": "- alpha\n- beta"},
    )

    titles = set(Task.objects.filter(project=project).values_list("title", flat=True))
    assert titles == {"Alpha", "Beta"}
    assert state.board_changed is True
    assert "Alpha" in result
    mock_parse.assert_called_once()


def test_search_and_summary_tools(user):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    TaskFactory.create(
        project=project,
        title="Write API tests",
        description="pytest for chat",
        created_by=user,
    )
    TaskFactory.create(
        project=project,
        title="Unrelated design",
        created_by=user,
    )
    tools, _state = build_board_tools(user=user, project_id=project.pk)

    found = _tool(tools, "search_tasks").invoke({"query": "pytest"})
    assert "Write API tests" in found
    assert "Unrelated design" not in found

    summary = _tool(tools, "get_board_summary").invoke({})
    assert project.name in summary
    assert "todo=" in summary


def test_chat_history_get_empty(user, api_client: APIClient):
    workspace = WorkspaceFactory.create(owner=user)
    project = ProjectFactory.create(workspace=workspace)
    api_client.force_authenticate(user)

    response = api_client.get("/api/chat/", {"project_id": project.pk})

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"messages": []}
