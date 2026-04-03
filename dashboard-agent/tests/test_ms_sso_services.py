import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth import ms_sso_services


class SsoServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_sso_navigates_and_authenticates(self) -> None:
        page = AsyncMock()
        page.goto = AsyncMock()

        original_authenticate = ms_sso_services.authenticate_sso
        authenticate_mock = AsyncMock()
        ms_sso_services.authenticate_sso = authenticate_mock
        try:
            ok = await ms_sso_services.login_sso(page, "user", "secret")
        finally:
            ms_sso_services.authenticate_sso = original_authenticate

        self.assertTrue(ok)
        page.goto.assert_awaited_once_with("https://sso.online.tableau.com/public/idp/SSO")
        authenticate_mock.assert_awaited_once_with(page, "user", "secret")


if __name__ == "__main__":
    unittest.main()
