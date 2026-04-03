import unittest
import sys
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
