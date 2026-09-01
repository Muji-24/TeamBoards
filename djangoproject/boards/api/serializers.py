from rest_framework import serializers

from djangoproject.boards.models import Activity
from djangoproject.boards.models import Comment
from djangoproject.boards.models import Label
from djangoproject.boards.models import Membership
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task
from djangoproject.boards.models import Workspace


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user_id", "email", "role"]
        read_only_fields = fields


class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "workspace", "name", "color"]
        read_only_fields = ["id"]

    def validate_workspace(self, workspace: Workspace) -> Workspace:
        user = self.context["request"].user
        if not workspace.members.filter(pk=user.pk).exists():
            raise serializers.ValidationError("You are not a member of this workspace.")
        return workspace


class WorkspaceSerializer(serializers.ModelSerializer):
    members = MembershipSerializer(source="memberships", many=True, read_only=True)
    my_role = serializers.SerializerMethodField()
    project_count = serializers.SerializerMethodField()
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "created_at",
            "members",
            "my_role",
            "project_count",
            "task_count",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "members",
            "my_role",
            "project_count",
            "task_count",
        ]

    def get_my_role(self, obj: Workspace) -> str | None:
        return obj.role_for(self.context["request"].user)

    def get_project_count(self, obj: Workspace) -> int:
        return int(getattr(obj, "project_count", 0) or 0)

    def get_task_count(self, obj: Workspace) -> int:
        return int(getattr(obj, "task_count", 0) or 0)


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ProjectSerializer(serializers.ModelSerializer):
    open_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "workspace", "name", "created_at", "open_count"]
        read_only_fields = ["id", "created_at", "open_count"]

    def validate_workspace(self, workspace: Workspace) -> Workspace:
        user = self.context["request"].user
        if not workspace.members.filter(pk=user.pk).exists():
            raise serializers.ValidationError(
                "You are not a member of this workspace.",
            )
        return workspace

    def get_open_count(self, obj: Project) -> int:
        return int(getattr(obj, "open_count", 0) or 0)


class TaskSerializer(serializers.ModelSerializer):
    assignee_email = serializers.EmailField(source="assignee.email", read_only=True, default=None)
    created_by_email = serializers.EmailField(
        source="created_by.email",
        read_only=True,
        default=None,
    )
    labels = LabelSerializer(many=True, read_only=True)
    label_ids = serializers.PrimaryKeyRelatedField(
        source="labels",
        many=True,
        queryset=Label.objects.all(),
        required=False,
        write_only=True,
    )
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "project",
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "assignee_email",
            "created_by",
            "created_by_email",
            "due_date",
            "labels",
            "label_ids",
            "comment_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_project(self, project: Project) -> Project:
        user = self.context["request"].user
        if not project.workspace.members.filter(pk=user.pk).exists():
            raise serializers.ValidationError(
                "You are not a member of this project's workspace.",
            )
        return project

    def validate(self, attrs: dict) -> dict:
        project = attrs.get("project")
        if project is None and self.instance is not None:
            project = self.instance.project
        assignee = attrs.get("assignee")
        if assignee is not None and project is not None:
            if not project.workspace.members.filter(pk=assignee.pk).exists():
                raise serializers.ValidationError(
                    {"assignee": "Assignee must be a member of this workspace."},
                )
        labels = attrs.get("labels")
        if labels is not None and project is not None:
            bad = [label.pk for label in labels if label.workspace_id != project.workspace_id]
            if bad:
                raise serializers.ValidationError(
                    {"label_ids": "Labels must belong to this workspace."},
                )
        return attrs

    def get_comment_count(self, obj: Task) -> int:
        return int(getattr(obj, "comment_count", 0) or 0)


class CommentSerializer(serializers.ModelSerializer):
    author_email = serializers.EmailField(source="author.email", read_only=True, default=None)

    class Meta:
        model = Comment
        fields = ["id", "task", "author", "author_email", "body", "created_at"]
        read_only_fields = ["id", "task", "author", "author_email", "created_at"]


class ActivitySerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = Activity
        fields = [
            "id",
            "workspace",
            "project",
            "task",
            "actor",
            "actor_email",
            "verb",
            "summary",
            "created_at",
        ]
        read_only_fields = fields
