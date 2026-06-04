import unittest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autocross_login.common import authenticate_microsoft_sso


class _HiddenField:
    async def wait_for(self, timeout: int) -> None:
        raise TimeoutError("not visible")


class _VisibleField:
    def __init__(self) -> None:
        self.filled = []

    async def wait_for(self, timeout: int) -> None:
        return None

    async def fill(self, value: str) -> None:
        self.filled.append(value)


class _Button:
    def __init__(self) -> None:
        self.clicked = False

    async def click(self) -> None:
        self.clicked = True


class _InvisibleStaySignedIn:
    async def is_visible(self, timeout: int) -> bool:
        return False


class _AlreadyLoggedInPage:
    def __init__(self) -> None:
        self.get_by_role_calls = []
        self.wait_for_load_state = AsyncMock()

    def get_by_role(self, role: str, name: str):
        self.get_by_role_calls.append((role, name))
        return _HiddenField()


class _PasswordOnlyPage:
    url = "https://login.microsoftonline.com/common/login"

    def __init__(self) -> None:
        self.username = _HiddenField()
        self.password = _VisibleField()
        self.sign_in = _Button()
        self.wait_for_load_state = AsyncMock()
        self.wait_for_url = AsyncMock()

    def get_by_role(self, role: str, name: str):
        if role == "textbox" and name == "username@domain.regn.net":
            return self.username
        if role == "textbox" and name == "Enter the password for":
            return self.password
        if role == "button" and name == "Sign in":
            return self.sign_in
        raise AssertionError((role, name))

    def locator(self, selector: str):
        return _InvisibleStaySignedIn()


class CommonLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticate_microsoft_sso_skips_when_username_field_absent(self) -> None:
        page = _AlreadyLoggedInPage()

        await authenticate_microsoft_sso(page, "user@example.com", "secret")

        self.assertEqual(
            page.get_by_role_calls,
            [("textbox", "username@domain.regn.net")],
        )
        page.wait_for_load_state.assert_not_called()

    async def test_authenticate_microsoft_sso_handles_password_only_page(self) -> None:
        page = _PasswordOnlyPage()

        await authenticate_microsoft_sso(page, "user@example.com", "secret")

        self.assertEqual(page.password.filled, ["secret"])
        self.assertTrue(page.sign_in.clicked)
        page.wait_for_url.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
