from django.contrib import admin

from .models import Activity
from .models import Comment
from .models import Label
from .models import Membership
from .models import Project
from .models import Task
from .models import Workspace


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    inlines = (MembershipInline,)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "created_at")
    list_filter = ("workspace",)
    search_fields = ("name",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "priority", "assignee", "due_date")
    list_filter = ("status", "priority", "project")
    search_fields = ("title",)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "color")
    list_filter = ("workspace",)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("task", "author", "created_at")
    search_fields = ("body",)


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("summary", "verb", "workspace", "actor", "created_at")
    list_filter = ("verb", "workspace")
