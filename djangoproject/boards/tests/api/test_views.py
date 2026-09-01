from __future__ import annotations

from http import HTTPStatus

import pytest
from rest_framework.test import APIClient

from djangoproject.boards.models import Membership
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task
from djangoproject.boards.models import Workspace
from djangoproject.boards.tests.factories import ProjectFactory
from djangoproject.boards.tests.factories import TaskFactory
from djangoproject.boards.tests.factories import WorkspaceFactory
from djangoproject.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


class TestWorkspaceAPI:
    def test_create_makes_caller_owner(self, user, api_client: APIClient):
        api_client.force_authenticate(user)
        response = api_client.post("/api/workspaces/", {"name": "Acme"}, format="json")

        assert response.status_code == HTTPStatus.CREATED
        workspace = Workspace.objects.get(pk=response.data["id"])
        assert workspace.role_for(user) == Membership.Role.OWNER
        assert response.data["my_role"] == Membership.Role.OWNER

    def test_list_hides_other_teams(self, user, api_client: APIClient):
        mine = WorkspaceFactory.create(owner=user)
        WorkspaceFactory.create()
        api_client.force_authenticate(user)

        response = api_client.get("/api/workspaces/")

        assert response.status_code == HTTPStatus.OK
        ids = {row["id"] for row in response.data}
        assert ids == {mine.pk}

    def test_anonymous_is_rejected(self, api_client: APIClient):
        response = api_client.get("/api/workspaces/")
        # SessionAuthentication makes DRF return 403 (not 401) when logged out.
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_member_cannot_delete(self, user, api_client: APIClient):
        owner = UserFactory.create()
        workspace = WorkspaceFactory.create(owner=owner)
        Membership.objects.create(
            workspace=workspace,
            user=user,
            role=Membership.Role.MEMBER,
        )
        api_client.force_authenticate(user)

        response = api_client.delete(f"/api/workspaces/{workspace.pk}/")

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert Workspace.objects.filter(pk=workspace.pk).exists()

    def test_owner_can_add_member(self, user, api_client: APIClient):
        workspace = WorkspaceFactory.create(owner=user)
        invitee = UserFactory.create()
        api_client.force_authenticate(user)

        response = api_client.post(
            f"/api/workspaces/{workspace.pk}/add_member/",
            {"email": invitee.email},
            format="json",
        )

        assert response.status_code == HTTPStatus.CREATED
        assert workspace.role_for(invitee) == Membership.Role.MEMBER


class TestProjectAPI:
    def test_create_in_own_workspace(self, user, api_client: APIClient):
        workspace = WorkspaceFactory.create(owner=user)
        api_client.force_authenticate(user)

        response = api_client.post(
            "/api/projects/",
            {"workspace": workspace.pk, "name": "Website"},
            format="json",
        )

        assert response.status_code == HTTPStatus.CREATED
        assert Project.objects.filter(name="Website", workspace=workspace).exists()

    def test_create_in_foreign_workspace_rejected(self, user, api_client: APIClient):
        foreign = WorkspaceFactory.create()
        api_client.force_authenticate(user)

        response = api_client.post(
            "/api/projects/",
            {"workspace": foreign.pk, "name": "Nope"},
            format="json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert not Project.objects.filter(name="Nope").exists()


class TestTaskAPI:
    def test_create_and_move_status(self, user, api_client: APIClient):
        workspace = WorkspaceFactory.create(owner=user)
        project = ProjectFactory.create(workspace=workspace)
        api_client.force_authenticate(user)

        created = api_client.post(
            "/api/tasks/",
            {"project": project.pk, "title": "Write copy"},
            format="json",
        )
        assert created.status_code == HTTPStatus.CREATED
        task_id = created.data["id"]
        assert created.data["status"] == Task.Status.TODO
        assert created.data["created_by"] == user.pk

        patched = api_client.patch(
            f"/api/tasks/{task_id}/",
            {"status": Task.Status.DOING},
            format="json",
        )
        assert patched.status_code == HTTPStatus.OK
        assert patched.data["status"] == Task.Status.DOING

    def test_comment_and_dashboard(self, user, api_client: APIClient):
        workspace = WorkspaceFactory.create(owner=user)
        project = ProjectFactory.create(workspace=workspace)
        api_client.force_authenticate(user)
        created = api_client.post(
            "/api/tasks/",
            {"project": project.pk, "title": "Ship", "priority": "high"},
            format="json",
        )
        task_id = created.data["id"]
        note = api_client.post(
            f"/api/tasks/{task_id}/comments/",
            {"body": "Need review"},
            format="json",
        )
        assert note.status_code == HTTPStatus.CREATED
        listed = api_client.get(f"/api/tasks/{task_id}/comments/")
        assert listed.data[0]["body"] == "Need review"

        dash = api_client.get(f"/api/workspaces/{workspace.pk}/dashboard/")
        assert dash.status_code == HTTPStatus.OK
        assert dash.data["counts"]["todo"] >= 1
        assert any("Created" in row["summary"] for row in dash.data["activity"])

        labels = api_client.get(f"/api/labels/?workspace={workspace.pk}")
        assert labels.status_code == HTTPStatus.OK
        assert {row["name"] for row in labels.data} >= {"Bug", "Feature", "Chore"}

        search = api_client.get(f"/api/tasks/?project={project.pk}&q=Ship")
        assert {row["id"] for row in search.data} == {task_id}

    def test_foreign_task_is_hidden(self, user, api_client: APIClient):
        task = TaskFactory.create()
        api_client.force_authenticate(user)

        response = api_client.get(f"/api/tasks/{task.pk}/")

        assert response.status_code == HTTPStatus.NOT_FOUND
