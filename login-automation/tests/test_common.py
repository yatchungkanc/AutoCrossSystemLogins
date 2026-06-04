import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autocross_login.common import authenticate_microsoft_sso


class _HiddenField:
    async def wait_for(self, timeout: int) -> None:
        raise TimeoutError("not visible")


class _AlreadyLoggedInPage:
    def __init__(self) -> None:
        self.get_by_role_calls = []
        self.wait_for_load_state = AsyncMock()

    def get_by_role(self, role: str, name: str):
        self.get_by_role_calls.append((role, name))
        return _HiddenField()


class CommonLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticate_microsoft_sso_skips_when_username_field_absent(self) -> None:
        page = _AlreadyLoggedInPage()

        await authenticate_microsoft_sso(page, "user@example.com", "secret")

        self.assertEqual(
            page.get_by_role_calls,
            [("textbox", "username@domain.regn.net")],
        )
        page.wait_for_load_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
