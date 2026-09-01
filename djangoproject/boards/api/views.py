from django.db.models import Count
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from djangoproject.boards.models import DEFAULT_LABELS
from djangoproject.boards.models import Activity
from djangoproject.boards.models import Label
from djangoproject.boards.models import Membership
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task
from djangoproject.boards.models import Workspace
from djangoproject.boards.models import log_activity
from djangoproject.users.models import User

from .serializers import ActivitySerializer
from .serializers import AddMemberSerializer
from .serializers import CommentSerializer
from .serializers import LabelSerializer
from .serializers import MembershipSerializer
from .serializers import ProjectSerializer
from .serializers import TaskSerializer
from .serializers import WorkspaceSerializer


class WorkspaceViewSet(ModelViewSet):
    serializer_class = WorkspaceSerializer
    queryset = Workspace.objects.all()

    def get_queryset(self):
        return (
            Workspace.objects.filter(members=self.request.user)
            .prefetch_related("memberships__user")
            .annotate(
                project_count=Count("projects", distinct=True),
                task_count=Count("projects__tasks", distinct=True),
            )
            .distinct()
        )

    def perform_create(self, serializer):
        workspace = serializer.save()
        Membership.objects.create(
            workspace=workspace,
            user=self.request.user,
            role=Membership.Role.OWNER,
        )
        Label.objects.bulk_create(
            [
                Label(workspace=workspace, name=name, color=color)
                for name, color in DEFAULT_LABELS
            ],
        )

    def perform_destroy(self, instance):
        if instance.role_for(self.request.user) != Membership.Role.OWNER:
            raise PermissionDenied
        instance.delete()

    @action(detail=True, methods=["post"])
    def add_member(self, request, pk=None):
        workspace = self.get_object()
        if workspace.role_for(request.user) != Membership.Role.OWNER:
            raise PermissionDenied

        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise ValidationError(
                {"email": ["No user with this email exists."]},
            ) from exc

        if Membership.objects.filter(workspace=workspace, user=user).exists():
            raise ValidationError({"email": ["This user is already a member."]})

        membership = Membership.objects.create(
            workspace=workspace,
            user=user,
            role=Membership.Role.MEMBER,
        )
        return Response(
            MembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        workspace = self.get_object()
        tasks = Task.objects.filter(project__workspace=workspace)
        today = timezone.localdate()
        counts = {
            "todo": tasks.filter(status=Task.Status.TODO).count(),
            "doing": tasks.filter(status=Task.Status.DOING).count(),
            "done": tasks.filter(status=Task.Status.DONE).count(),
            "overdue": tasks.exclude(status=Task.Status.DONE)
            .filter(due_date__lt=today)
            .count(),
            "unassigned": tasks.filter(assignee__isnull=True)
            .exclude(status=Task.Status.DONE)
            .count(),
        }
        activity = Activity.objects.filter(workspace=workspace).select_related(
            "actor",
            "task",
            "project",
        )[:20]
        return Response(
            {
                "counts": counts,
                "activity": ActivitySerializer(activity, many=True).data,
            },
        )


class ProjectViewSet(ModelViewSet):
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()

    def get_queryset(self):
        queryset = (
            Project.objects.filter(workspace__members=self.request.user)
            .select_related("workspace")
            .annotate(
                open_count=Count(
                    "tasks",
                    filter=~Q(tasks__status=Task.Status.DONE),
                ),
            )
        )
        workspace_id = self.request.query_params.get("workspace")
        if workspace_id:
            queryset = queryset.filter(workspace_id=workspace_id)
        return queryset


class LabelViewSet(ModelViewSet):
    serializer_class = LabelSerializer
    queryset = Label.objects.all()

    def get_queryset(self):
        queryset = Label.objects.filter(workspace__members=self.request.user)
        workspace_id = self.request.query_params.get("workspace")
        if workspace_id:
            queryset = queryset.filter(workspace_id=workspace_id)
        return queryset

    def perform_destroy(self, instance):
        if instance.workspace.role_for(self.request.user) != Membership.Role.OWNER:
            raise PermissionDenied
        instance.delete()


class TaskViewSet(ModelViewSet):
    serializer_class = TaskSerializer
    queryset = Task.objects.all()

    def get_queryset(self):
        queryset = (
            Task.objects.filter(project__workspace__members=self.request.user)
            .select_related("project", "assignee", "created_by")
            .prefetch_related("labels")
            .annotate(comment_count=Count("comments"))
        )
        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        q = self.request.query_params.get("q")
        if q:
            queryset = queryset.filter(
                Q(title__icontains=q) | Q(description__icontains=q),
            )
        assignee = self.request.query_params.get("assignee")
        if assignee == "me":
            queryset = queryset.filter(assignee=self.request.user)
        elif assignee == "none":
            queryset = queryset.filter(assignee__isnull=True)
        elif assignee:
            queryset = queryset.filter(assignee_id=assignee)
        priority = self.request.query_params.get("priority")
        if priority:
            queryset = queryset.filter(priority=priority)
        label = self.request.query_params.get("label")
        if label:
            queryset = queryset.filter(labels__pk=label)
        return queryset

    def perform_create(self, serializer):
        task = serializer.save(created_by=self.request.user)
        log_activity(
            workspace=task.project.workspace,
            project=task.project,
            task=task,
            actor=self.request.user,
            verb=Activity.Verb.CREATED,
            summary=f"Created #{task.pk} {task.title}",
        )

    def perform_update(self, serializer):
        before = Task.objects.get(pk=serializer.instance.pk)
        task = serializer.save()
        if before.status != task.status:
            log_activity(
                workspace=task.project.workspace,
                project=task.project,
                task=task,
                actor=self.request.user,
                verb=Activity.Verb.MOVED,
                summary=f"Moved #{task.pk} to {task.status}",
            )
        elif before.assignee_id != task.assignee_id:
            who = task.assignee.email if task.assignee else "unassigned"
            log_activity(
                workspace=task.project.workspace,
                project=task.project,
                task=task,
                actor=self.request.user,
                verb=Activity.Verb.ASSIGNED,
                summary=f"Assigned #{task.pk} to {who}",
            )
        else:
            log_activity(
                workspace=task.project.workspace,
                project=task.project,
                task=task,
                actor=self.request.user,
                verb=Activity.Verb.UPDATED,
                summary=f"Updated #{task.pk} {task.title}",
            )

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        task = self.get_object()
        if request.method == "GET":
            comments = task.comments.select_related("author")
            return Response(CommentSerializer(comments, many=True).data)
        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(task=task, author=request.user)
        log_activity(
            workspace=task.project.workspace,
            project=task.project,
            task=task,
            actor=request.user,
            verb=Activity.Verb.COMMENTED,
            summary=f"Commented on #{task.pk}",
        )
        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)
