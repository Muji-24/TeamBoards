from __future__ import annotations

from factory import Faker
from factory import SubFactory
from factory import post_generation
from factory.django import DjangoModelFactory

from djangoproject.boards.models import DEFAULT_LABELS
from djangoproject.boards.models import Label
from djangoproject.boards.models import Membership
from djangoproject.boards.models import Project
from djangoproject.boards.models import Task
from djangoproject.boards.models import Workspace
from djangoproject.users.tests.factories import UserFactory


class WorkspaceFactory(DjangoModelFactory[Workspace]):
    name = Faker("company")

    class Meta:
        model = Workspace
        skip_postgeneration_save = True

    @post_generation
    def owner(self, create: bool, extracted, **kwargs):  # noqa: FBT001
        if not create:
            return
        user = extracted or UserFactory.create()
        Membership.objects.create(
            workspace=self,
            user=user,
            role=Membership.Role.OWNER,
        )
        Label.objects.bulk_create(
            [Label(workspace=self, name=name, color=color) for name, color in DEFAULT_LABELS],
        )


class ProjectFactory(DjangoModelFactory[Project]):
    name = Faker("bs")
    workspace = SubFactory(WorkspaceFactory)

    class Meta:
        model = Project


class TaskFactory(DjangoModelFactory[Task]):
    title = Faker("sentence", nb_words=4)
    project = SubFactory(ProjectFactory)
    created_by = SubFactory(UserFactory)

    class Meta:
        model = Task
