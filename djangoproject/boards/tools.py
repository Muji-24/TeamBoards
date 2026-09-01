"""Django-backed tools the model is allowed to call.

A LangChain tool is a Python function plus a schema. Gemini never talks to
Postgres itself — it asks to run `create_task`, and *this* code does the ORM
write after checking membership.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import date

from langchain_core.tools import BaseTool
from langchain_core.tools import tool

from djangoproject.boards.models import Activity
from djangoproject.boards.models import Comment
from djangoproject.boards.models import Label
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task
from djangoproject.boards.models import log_activity
from djangoproject.boards.schemas import AddCommentInput
from djangoproject.boards.schemas import ApplyLabelInput
from djangoproject.boards.schemas import AssignTaskInput
from djangoproject.boards.schemas import CreateTasksFromNotesInput
from djangoproject.boards.schemas import ListTasksInput
from djangoproject.boards.schemas import SetDueDateInput
from djangoproject.boards.schemas import SetPriorityInput
from djangoproject.boards.schemas import TaskDraft
from djangoproject.boards.schemas import UpdateTaskStatusInput
from djangoproject.users.models import User

NO_PROJECT = (
    "Open a project board you belong to first. "
    "I cannot list or change tasks without one."
)


@dataclass
class ToolState:
    board_changed: bool = False
    actions: list[str] = field(default_factory=list)


def _format_task(task: Task) -> str:
    bits = [f"#{task.pk}", f"[{task.status}]", f"({task.priority})", task.title]
    if task.assignee_id:
        bits.append(f"@{task.assignee.email}")
    if task.due_date:
        bits.append(f"due {task.due_date.isoformat()}")
    labels = list(task.labels.values_list("name", flat=True))
    if labels:
        bits.append("{" + ", ".join(labels) + "}")
    return " ".join(bits)


def _project_for(user, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    return Project.objects.filter(
        pk=project_id,
        workspace__members=user,
    ).first()


def _task_for(user, project_id: int | None, task_id: int) -> Task | str:
    project = _project_for(user, project_id)
    if project is None:
        return NO_PROJECT
    task = (
        Task.objects.filter(pk=task_id, project=project)
        .select_related("assignee")
        .prefetch_related("labels")
        .first()
    )
    if task is None:
        return f"No task #{task_id} on this board."
    return task


def _parse_due(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def list_tasks_action(user, project_id: int | None, status: str | None) -> str:
    project = _project_for(user, project_id)
    if project is None:
        return NO_PROJECT
    tasks = (
        Task.objects.filter(project=project)
        .select_related("assignee")
        .prefetch_related("labels")
        .order_by("status", "id")
    )
    if status:
        tasks = tasks.filter(status=status)
    if not tasks:
        return "No tasks match."
    return "\n".join(_format_task(task) for task in tasks)


def create_task_action(
    user,
    project_id: int | None,
    state: ToolState,
    draft: TaskDraft,
) -> str:
    project = _project_for(user, project_id)
    if project is None:
        return NO_PROJECT
    assignee = None
    if draft.assignee_email:
        assignee = project.workspace.members.filter(
            email__iexact=draft.assignee_email.strip(),
        ).first()
        if assignee is None:
            return f"No member with email {draft.assignee_email}."
    due = None
    if draft.due_date:
        try:
            due = _parse_due(draft.due_date)
        except ValueError:
            return "due_date must be YYYY-MM-DD."
    task = Task.objects.create(
        project=project,
        title=draft.title.strip(),
        status=draft.status,
        description=draft.description,
        priority=draft.priority,
        due_date=due,
        assignee=assignee,
        created_by=user,
    )
    log_activity(
        workspace=project.workspace,
        project=project,
        task=task,
        actor=user,
        verb=Activity.Verb.CREATED,
        summary=f"Created #{task.pk} {task.title}",
    )
    state.board_changed = True
    summary = f"Created {_format_task(task)}"
    state.actions.append(summary)
    return summary


def update_task_status_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    status: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    task.status = status
    task.save(update_fields=["status", "updated_at"])
    log_activity(
        workspace=task.project.workspace,
        project=task.project,
        task=task,
        actor=user,
        verb=Activity.Verb.MOVED,
        summary=f"Moved #{task.pk} to {task.status}",
    )
    state.board_changed = True
    summary = f"Moved {_format_task(task)}"
    state.actions.append(summary)
    return summary


def create_tasks_from_notes_action(
    user,
    project_id: int | None,
    state: ToolState,
    notes: str,
) -> str:
    project = _project_for(user, project_id)
    if project is None:
        return NO_PROJECT
    from djangoproject.boards.llm import parse_proposed_tasks  # noqa: PLC0415

    parsed = parse_proposed_tasks(notes)
    if not parsed.tasks:
        return "I could not extract any tasks from that text."
    created = []
    for draft in parsed.tasks:
        task = Task.objects.create(
            project=project,
            title=draft.title.strip(),
            status=draft.status,
            description=draft.description,
            priority=draft.priority,
            created_by=user,
        )
        created.append(_format_task(task))
        log_activity(
            workspace=project.workspace,
            project=project,
            task=task,
            actor=user,
            verb=Activity.Verb.CREATED,
            summary=f"Created #{task.pk} {task.title}",
        )
    state.board_changed = True
    summary = "Created " + "; ".join(created)
    state.actions.append(summary)
    return summary


def assign_task_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    email: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    email = email.strip()
    assignee = None
    if email:
        assignee = User.objects.filter(
            email__iexact=email,
            workspaces=task.project.workspace,
        ).first()
        if assignee is None:
            return f"No member with email {email}."
    task.assignee = assignee
    task.save(update_fields=["assignee", "updated_at"])
    who = assignee.email if assignee else "unassigned"
    log_activity(
        workspace=task.project.workspace,
        project=task.project,
        task=task,
        actor=user,
        verb=Activity.Verb.ASSIGNED,
        summary=f"Assigned #{task.pk} to {who}",
    )
    state.board_changed = True
    summary = f"Assigned {_format_task(task)}"
    state.actions.append(summary)
    return summary


def set_due_date_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    due_date: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    try:
        task.due_date = _parse_due(due_date)
    except ValueError:
        return "due_date must be YYYY-MM-DD."
    task.save(update_fields=["due_date", "updated_at"])
    state.board_changed = True
    summary = f"Due date for {_format_task(task)}"
    state.actions.append(summary)
    return summary


def set_priority_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    priority: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    task.priority = priority
    task.save(update_fields=["priority", "updated_at"])
    state.board_changed = True
    summary = f"Priority {_format_task(task)}"
    state.actions.append(summary)
    return summary


def add_comment_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    body: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    Comment.objects.create(task=task, author=user, body=body.strip())
    log_activity(
        workspace=task.project.workspace,
        project=task.project,
        task=task,
        actor=user,
        verb=Activity.Verb.COMMENTED,
        summary=f"Commented on #{task.pk}",
    )
    state.board_changed = True
    summary = f"Commented on #{task.pk}"
    state.actions.append(summary)
    return summary


def apply_label_action(
    user,
    project_id: int | None,
    state: ToolState,
    *,
    task_id: int,
    label_name: str,
) -> str:
    task = _task_for(user, project_id, task_id)
    if isinstance(task, str):
        return task
    label = Label.objects.filter(
        workspace=task.project.workspace,
        name__iexact=label_name.strip(),
    ).first()
    if label is None:
        names = ", ".join(
            Label.objects.filter(workspace=task.project.workspace).values_list(
                "name",
                flat=True,
            ),
        )
        return f"No label named {label_name}. Available: {names or '(none)'}"
    task.labels.add(label)
    state.board_changed = True
    summary = f"Labeled #{task.pk} with {label.name}"
    state.actions.append(summary)
    return summary


def build_board_tools(
    *,
    user,
    project_id: int | None,
) -> tuple[list[BaseTool], ToolState]:
    state = ToolState()

    @tool(args_schema=ListTasksInput)
    def list_tasks(status: str | None = None) -> str:
        """List live cards on the current board. Filter by column if given."""
        return list_tasks_action(user, project_id, status)

    @tool(args_schema=TaskDraft)
    def create_task(  # noqa: PLR0913, PLR0917
        title: str,
        status: str = "todo",
        description: str = "",
        priority: str = "medium",
        due_date: str | None = None,
        assignee_email: str | None = None,
    ) -> str:
        """Create one card. Use this when the user wants a single new task."""
        return create_task_action(
            user,
            project_id,
            state,
            TaskDraft(
                title=title,
                status=status,  # type: ignore[arg-type]
                description=description,
                priority=priority,  # type: ignore[arg-type]
                due_date=due_date,
                assignee_email=assignee_email,
            ),
        )

    @tool(args_schema=UpdateTaskStatusInput)
    def update_task_status(task_id: int, status: str) -> str:
        """Move a card to todo, doing, or done. Use the numeric task id."""
        return update_task_status_action(
            user,
            project_id,
            state,
            task_id=task_id,
            status=status,
        )

    @tool(args_schema=CreateTasksFromNotesInput)
    def create_tasks_from_notes(notes: str) -> str:
        """Extract several cards from a pasted list using structured output."""
        return create_tasks_from_notes_action(user, project_id, state, notes)

    @tool(args_schema=AssignTaskInput)
    def assign_task(task_id: int, email: str) -> str:
        """Assign a card to a workspace member by email, or unassign."""
        return assign_task_action(
            user,
            project_id,
            state,
            task_id=task_id,
            email=email,
        )

    @tool(args_schema=SetDueDateInput)
    def set_due_date(task_id: int, due_date: str) -> str:
        """Set or clear a card's due date (YYYY-MM-DD)."""
        return set_due_date_action(
            user,
            project_id,
            state,
            task_id=task_id,
            due_date=due_date,
        )

    @tool(args_schema=SetPriorityInput)
    def set_priority(task_id: int, priority: str) -> str:
        """Set card priority: low, medium, high, or urgent."""
        return set_priority_action(
            user,
            project_id,
            state,
            task_id=task_id,
            priority=priority,
        )

    @tool(args_schema=AddCommentInput)
    def add_comment(task_id: int, body: str) -> str:
        """Leave a comment on a card."""
        return add_comment_action(
            user,
            project_id,
            state,
            task_id=task_id,
            body=body,
        )

    @tool(args_schema=ApplyLabelInput)
    def apply_label(task_id: int, label_name: str) -> str:
        """Attach an existing workspace label (Bug, Feature, Chore, …)."""
        return apply_label_action(
            user,
            project_id,
            state,
            task_id=task_id,
            label_name=label_name,
        )

    return (
        [
            list_tasks,
            create_task,
            update_task_status,
            create_tasks_from_notes,
            assign_task,
            set_due_date,
            set_priority,
            add_comment,
            apply_label,
        ],
        state,
    )
