from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Workspace(models.Model):
    """A team. Everything else hangs off this."""

    name = models.CharField(_("Name"), max_length=255)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="Membership",
        related_name="workspaces",
        verbose_name=_("Members"),
    )

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    def role_for(self, user) -> str | None:
        """Return this user's role in the workspace, or None if not a member."""
        membership = self.memberships.filter(user=user).first()
        return membership.role if membership else None


class Membership(models.Model):
    """Who belongs to a workspace, and with what role.

    This is a 'through' table: a ManyToMany between User and Workspace
    that also stores extra data (role).
    """

    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        MEMBER = "member", _("Member")

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Workspace"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
        verbose_name=_("User"),
    )
    role = models.CharField(
        _("Role"),
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                name="boards_unique_workspace_member",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.workspace} ({self.role})"


class Project(models.Model):
    """A board inside a workspace (e.g. 'Website', 'Mobile')."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name=_("Workspace"),
    )
    name = models.CharField(_("Name"), max_length=255)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} ({self.workspace})"


class Task(models.Model):
    """A card on a project board."""

    class Status(models.TextChoices):
        TODO = "todo", _("To do")
        DOING = "doing", _("Doing")
        DONE = "done", _("Done")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name=_("Project"),
    )
    title = models.CharField(_("Title"), max_length=255)
    description = models.TextField(_("Description"), blank=True)
    status = models.CharField(
        _("Status"),
        max_length=20,
        choices=Status.choices,
        default=Status.TODO,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        verbose_name=_("Assignee"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
        verbose_name=_("Created by"),
    )
    due_date = models.DateField(_("Due date"), null=True, blank=True)
    priority = models.CharField(
        _("Priority"),
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    labels = models.ManyToManyField(
        "Label",
        related_name="tasks",
        blank=True,
        verbose_name=_("Labels"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title


class Label(models.Model):
    """A workspace tag applied to cards (Bug, Feature, …)."""

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="labels",
        verbose_name=_("Workspace"),
    )
    name = models.CharField(_("Name"), max_length=40)
    color = models.CharField(_("Color"), max_length=16, default="#66707f")

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "name"),
                name="boards_unique_workspace_label",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.workspace})"


class Comment(models.Model):
    """A note on a card. Author is always a workspace member."""

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("Task"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_comments",
        verbose_name=_("Author"),
    )
    body = models.TextField(_("Body"))
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"Comment on {self.task_id}"


class Activity(models.Model):
    """An event in a workspace: created, moved, commented, assigned."""

    class Verb(models.TextChoices):
        CREATED = "created", _("Created")
        MOVED = "moved", _("Moved")
        UPDATED = "updated", _("Updated")
        COMMENTED = "commented", _("Commented")
        ASSIGNED = "assigned", _("Assigned")

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="activities",
        verbose_name=_("Workspace"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name=_("Project"),
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name=_("Task"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="board_activities",
        verbose_name=_("Actor"),
    )
    verb = models.CharField(_("Verb"), max_length=20, choices=Verb.choices)
    summary = models.CharField(_("Summary"), max_length=255)
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.summary


def log_activity(  # noqa: PLR0913
    *,
    workspace: Workspace,
    actor,
    verb: str,
    summary: str,
    project: Project | None = None,
    task: Task | None = None,
) -> Activity:
    return Activity.objects.create(
        workspace=workspace,
        project=project,
        task=task,
        actor=actor,
        verb=verb,
        summary=summary,
    )


class ChatThread(models.Model):
    """One LangGraph conversation per user and board (or global if no board)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_threads",
        verbose_name=_("User"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chat_threads",
        verbose_name=_("Project"),
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated at"), auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "project"),
                condition=models.Q(project__isnull=False),
                name="boards_unique_user_project_chat",
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(project__isnull=True),
                name="boards_unique_user_global_chat",
            ),
        ]

    def __str__(self) -> str:
        board = self.project_id or "global"
        return f"Chat {self.user_id} / {board}"


class ChatMessage(models.Model):
    """Persisted human/assistant turns. Tool calls are not stored as bubbles."""

    class Role(models.TextChoices):
        HUMAN = "human", _("Human")
        AI = "ai", _("Assistant")

    thread = models.ForeignKey(
        ChatThread,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name=_("Thread"),
    )
    role = models.CharField(_("Role"), max_length=8, choices=Role.choices)
    content = models.TextField(_("Content"))
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.role} in thread {self.thread_id}"


DEFAULT_LABELS = (
    ("Bug", "#e23d2a"),
    ("Feature", "#2f6fed"),
    ("Chore", "#66707f"),
)
