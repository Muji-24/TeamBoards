from django.urls import resolve
from django.urls import reverse


def test_workspace_list():
    assert reverse("api:workspace-list") == "/api/workspaces/"
    assert resolve("/api/workspaces/").view_name == "api:workspace-list"


def test_project_list():
    assert reverse("api:project-list") == "/api/projects/"
    assert resolve("/api/projects/").view_name == "api:project-list"


def test_task_list():
    assert reverse("api:task-list") == "/api/tasks/"
    assert resolve("/api/tasks/").view_name == "api:task-list"


def test_label_list():
    assert reverse("api:label-list") == "/api/labels/"
    assert resolve("/api/labels/").view_name == "api:label-list"
