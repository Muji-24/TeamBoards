"""Pydantic shapes the model must fill — this is structured output.

Free-text replies are easy to misread ("add a card maybe called docs?").
A schema says: title is a string, status is one of three values. LangChain
sends that schema to Gemini as a tool/function definition.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic import Field

TaskStatusName = Literal["todo", "doing", "done"]
PriorityName = Literal["low", "medium", "high", "urgent"]


class TaskDraft(BaseModel):
    """One card to write to the board."""

    title: str = Field(description="Short card title")
    status: TaskStatusName = Field(
        default="todo",
        description="Column: todo, doing, or done",
    )
    description: str = Field(default="", description="Optional details")
    priority: PriorityName = Field(default="medium")
    due_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    assignee_email: str | None = Field(
        default=None,
        description="Workspace member email to assign",
    )


class ProposedTaskList(BaseModel):
    """Several cards extracted from a pasted list or paragraph."""

    tasks: list[TaskDraft] = Field(description="Tasks to create")


class ListTasksInput(BaseModel):
    status: TaskStatusName | None = Field(
        default=None,
        description="If set, only list cards in this column",
    )


class UpdateTaskStatusInput(BaseModel):
    task_id: int = Field(description="Numeric id of the card, e.g. 12")
    status: TaskStatusName = Field(description="Column to move the card to")


class CreateTasksFromNotesInput(BaseModel):
    notes: str = Field(
        description="Messy list or paragraph of work to turn into cards",
    )


class AssignTaskInput(BaseModel):
    task_id: int
    email: str = Field(description="Member email, or empty to unassign")


class SetDueDateInput(BaseModel):
    task_id: int
    due_date: str = Field(description="ISO date YYYY-MM-DD, or empty to clear")


class SetPriorityInput(BaseModel):
    task_id: int
    priority: PriorityName


class AddCommentInput(BaseModel):
    task_id: int
    body: str


class ApplyLabelInput(BaseModel):
    task_id: int
    label_name: str = Field(description="Existing workspace label name, e.g. Bug")


class BoardReply(BaseModel):
    """Typed payload on the final SSE event so the UI can refresh the board."""

    message: str = Field(description="Short reply to show the user")
    board_changed: bool = Field(
        description="True if a task was created or moved",
    )
    actions: list[str] = Field(
        default_factory=list,
        description="What the tools actually did",
    )
