from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from djangoproject.boards.api.views import LabelViewSet
from djangoproject.boards.api.views import ProjectViewSet
from djangoproject.boards.api.views import TaskViewSet
from djangoproject.boards.api.views import WorkspaceViewSet
from djangoproject.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)
router.register("workspaces", WorkspaceViewSet)
router.register("projects", ProjectViewSet)
router.register("tasks", TaskViewSet)
router.register("labels", LabelViewSet)


app_name = "api"
urlpatterns = router.urls
