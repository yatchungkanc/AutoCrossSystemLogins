import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autocross_login import providers


class ProviderWrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_microsoft_sso_navigates_and_authenticates(self) -> None:
        page = AsyncMock()
        auth_mock = AsyncMock()
        original = providers.authenticate_microsoft_sso
        providers.authenticate_microsoft_sso = auth_mock
        try:
            ok = await providers.login_microsoft_sso(
                page,
                "user@example.com",
                "secret",
                login_url="https://login.example.test",
            )
        finally:
            providers.authenticate_microsoft_sso = original

        self.assertTrue(ok)
        page.goto.assert_awaited_once_with("https://login.example.test")
        auth_mock.assert_awaited_once_with(page, "user@example.com", "secret")

    async def test_login_cloudhealth_delegates_to_email_strategy(self) -> None:
        context = object()
        runner_mock = AsyncMock(return_value=True)
        original = providers.run_email_login_strategy
        providers.run_email_login_strategy = runner_mock
        try:
            ok = await providers.login_cloudhealth(context, "person@example.com")
        finally:
            providers.run_email_login_strategy = original

        self.assertTrue(ok)
        runner_mock.assert_awaited_once_with(
            context,
            "person@example.com",
            providers.CLOUDHEALTH_LOGIN,
        )

    def test_cloudhealth_redirect_complete_requires_app_domain(self) -> None:
        self.assertFalse(
            providers.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://sso.example.test/saml/redirect"
            )
        )
        self.assertFalse(
            providers.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://apps.cloudhealthtech.com/login"
            )
        )
        self.assertTrue(
            providers.CLOUDHEALTH_LOGIN.redirect_complete(
                "https://apps.cloudhealthtech.com/assets/overview"
            )
        )

    def test_cloudzero_redirect_rejects_auth_and_microsoft_domains(self) -> None:
        self.assertFalse(
            providers.CLOUDZERO_LOGIN.redirect_complete(
                "https://auth.cloudzero.com/u/login"
            )
        )
        self.assertFalse(
            providers.CLOUDZERO_LOGIN.redirect_complete(
                "https://login.microsoftonline.com/common/login"
            )
        )
        self.assertTrue(
            providers.CLOUDZERO_LOGIN.redirect_complete(
                "https://app.cloudzero.com/explorer"
            )
        )


if __name__ == "__main__":
    unittest.main()
