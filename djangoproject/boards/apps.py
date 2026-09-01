from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BoardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "djangoproject.boards"
    verbose_name = _("Boards")
