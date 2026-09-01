from http import HTTPStatus

import pytest
from rest_framework.test import APIClient

from djangoproject.users.models import User
from djangoproject.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


def test_register_returns_token(api_client: APIClient):
    response = api_client.post(
        "/api/auth/register/",
        {
            "email": "new@example.com",
            "password": "a-strong-pass",
            "name": "New",
        },
        format="json",
    )

    assert response.status_code == HTTPStatus.CREATED
    assert "token" in response.data
    assert User.objects.filter(email="new@example.com").exists()


def test_login_returns_token(api_client: APIClient):
    user = UserFactory.create(password="a-strong-pass")
    response = api_client.post(
        "/api/auth/login/",
        {"email": user.email, "password": "a-strong-pass"},
        format="json",
    )

    assert response.status_code == HTTPStatus.OK
    assert "token" in response.data
    assert response.data["email"] == user.email


def test_login_rejects_bad_password(api_client: APIClient):
    user = UserFactory.create(password="a-strong-pass")
    response = api_client.post(
        "/api/auth/login/",
        {"email": user.email, "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
