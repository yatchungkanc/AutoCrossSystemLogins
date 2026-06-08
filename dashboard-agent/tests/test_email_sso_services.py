import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth import email_sso_services


class EmailServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_cloudhealth_redirect_complete_requires_apps_domain(self) -> None:
        self.assertFalse(
            email_sso_services.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://sso.broadcom.com/saml/redirect"
            )
        )
        self.assertFalse(
            email_sso_services.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://apps.cloudhealthtech.com/login"
            )
        )
        self.assertTrue(
            email_sso_services.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://apps.cloudhealthtech.com/assets/overview"
            )
        )

    def test_cloudzero_redirect_complete_requires_cloudzero_app_domain(self) -> None:
        self.assertFalse(
            email_sso_services.CLOUDZERO_LOGIN.redirect_complete(
                "https://sso.example.com/saml/redirect"
            )
        )
        self.assertFalse(
            email_sso_services.CLOUDZERO_LOGIN.redirect_complete(
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            )
        )
        self.assertFalse(
            email_sso_services.CLOUDZERO_LOGIN.redirect_complete(
                "https://auth.cloudzero.com/u/login/"
            )
        )
        self.assertTrue(
            email_sso_services.CLOUDZERO_LOGIN.redirect_complete(
                "https://next.cloudzero.com/explorer?date_range=last_30_days"
            )
        )
        self.assertTrue(
            email_sso_services.CLOUDZERO_LOGIN.redirect_complete(
                "https://app.cloudzero.com/analytics/dashboards/32955/view"
            )
        )

    def test_cloudzero_initial_app_url_is_not_already_logged_in(self) -> None:
        self.assertFalse(
            email_sso_services.CLOUDZERO_LOGIN.already_logged_in(
                "https://app.cloudzero.com/"
            )
        )
        self.assertFalse(
            email_sso_services.CLOUDZERO_LOGIN.already_logged_in(
                "https://next.cloudzero.com/"
            )
        )
        self.assertTrue(
            email_sso_services.CLOUDZERO_LOGIN.already_logged_in(
                "https://next.cloudzero.com/explorer?date_range=last_30_days"
            )
        )

    def test_cloudzero_login_starts_on_next_domain(self) -> None:
        self.assertEqual(
            email_sso_services.CLOUDZERO_LOGIN.login_url,
            "https://next.cloudzero.com/",
        )

    async def test_login_cloudhealth_delegates_to_shared_email_strategy(self) -> None:
        context = object()

        original_runner = email_sso_services.run_email_login_strategy
        runner_mock = AsyncMock(return_value=True)
        email_sso_services.run_email_login_strategy = runner_mock
        try:
            ok = await email_sso_services.login_cloudhealth(context, "person@example.com")
        finally:
            email_sso_services.run_email_login_strategy = original_runner

        self.assertTrue(ok)
        runner_mock.assert_awaited_once_with(
            context,
            "person@example.com",
            email_sso_services.CLOUDHEALTH_LOGIN,
        )

    async def test_cloudzero_sso_helper_uses_credentials_on_microsoft_url(self) -> None:
        page = SimpleNamespace(url="https://login.microsoftonline.com/common")
        auth_mock = AsyncMock()
        original_authenticate = email_sso_services.authenticate_sso
        email_sso_services.authenticate_sso = auth_mock
        try:
            await email_sso_services._authenticate_if_on_microsoft_sso(
                page,
                "user@example.com",
                "secret",
            )
        finally:
            email_sso_services.authenticate_sso = original_authenticate

        auth_mock.assert_awaited_once_with(page, "user@example.com", "secret")

    async def test_cloudzero_sso_helper_skips_without_credentials(self) -> None:
        page = SimpleNamespace(url="https://login.microsoftonline.com/common")
        auth_mock = AsyncMock()
        original_authenticate = email_sso_services.authenticate_sso
        email_sso_services.authenticate_sso = auth_mock
        try:
            await email_sso_services._authenticate_if_on_microsoft_sso(page, "", "")
        finally:
            email_sso_services.authenticate_sso = original_authenticate

        auth_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
