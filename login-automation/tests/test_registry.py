import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autocross_login.models import AuthCredentials, AuthStrategySpec
from autocross_login.registry import LoginDispatcher


class LoginDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_auth_type_returns_false(self) -> None:
        dispatcher = LoginDispatcher(strategies={})

        ok = await dispatcher.login("missing", credentials=AuthCredentials())

        self.assertFalse(ok)

    async def test_missing_required_credentials_returns_false(self) -> None:
        strategy = AsyncMock(return_value=True)
        dispatcher = LoginDispatcher(
            strategies={
                "sso": AuthStrategySpec(
                    func=strategy,
                    target="page",
                    credentials=("username", "password"),
                )
            }
        )

        ok = await dispatcher.login(
            "sso",
            page=object(),
            credentials=AuthCredentials(username="user"),
        )

        self.assertFalse(ok)
        strategy.assert_not_awaited()

    async def test_optional_missing_credentials_skips_successfully(self) -> None:
        strategy = AsyncMock(return_value=True)
        dispatcher = LoginDispatcher(
            strategies={
                "cloudzero": AuthStrategySpec(
                    func=strategy,
                    target="context",
                    credentials=("cloudzero_email",),
                    optional=True,
                )
            }
        )

        ok = await dispatcher.login(
            "cloudzero",
            context=object(),
            credentials=AuthCredentials(),
        )

        self.assertTrue(ok)
        strategy.assert_not_awaited()

    async def test_page_strategy_dispatches_with_credentials(self) -> None:
        strategy = AsyncMock(return_value=True)
        page = object()
        dispatcher = LoginDispatcher(
            strategies={
                "sso": AuthStrategySpec(
                    func=strategy,
                    target="page",
                    credentials=("username", "password"),
                )
            }
        )

        ok = await dispatcher.login(
            "sso",
            page=page,
            credentials=AuthCredentials(username="user", password="secret"),
        )

        self.assertTrue(ok)
        strategy.assert_awaited_once_with(page, "user", "secret")

    async def test_strategy_dispatches_optional_credentials_when_available(self) -> None:
        strategy = AsyncMock(return_value=True)
        context = object()
        dispatcher = LoginDispatcher(
            strategies={
                "cloudzero": AuthStrategySpec(
                    func=strategy,
                    target="context",
                    credentials=("cloudzero_email",),
                    optional_credentials=("username", "password"),
                    optional=True,
                )
            }
        )

        ok = await dispatcher.login(
            "cloudzero",
            context=context,
            credentials=AuthCredentials(
                cloudzero_email="cloud@example.com",
                username="sso@example.com",
                password="secret",
            ),
        )

        self.assertTrue(ok)
        strategy.assert_awaited_once_with(
            context,
            "cloud@example.com",
            "sso@example.com",
            "secret",
        )

    async def test_strategy_uses_empty_optional_credentials_when_missing(self) -> None:
        strategy = AsyncMock(return_value=True)
        context = object()
        dispatcher = LoginDispatcher(
            strategies={
                "cloudzero": AuthStrategySpec(
                    func=strategy,
                    target="context",
                    credentials=("cloudzero_email",),
                    optional_credentials=("username", "password"),
                    optional=True,
                )
            }
        )

        ok = await dispatcher.login(
            "cloudzero",
            context=context,
            credentials=AuthCredentials(cloudzero_email="cloud@example.com"),
        )

        self.assertTrue(ok)
        strategy.assert_awaited_once_with(context, "cloud@example.com", "", "")

    async def test_cloudzero_dispatches_landing_url_when_available(self) -> None:
        strategy = AsyncMock(return_value=True)
        context = object()
        dispatcher = LoginDispatcher(
            strategies={
                "cloudzero": AuthStrategySpec(
                    func=strategy,
                    target="context",
                    credentials=("cloudzero_email",),
                    optional_credentials=("username", "password"),
                    optional=True,
                )
            }
        )

        ok = await dispatcher.login(
            "cloudzero",
            context=context,
            credentials=AuthCredentials(
                cloudzero_email="cloud@example.com",
                username="sso@example.com",
                password="secret",
            ),
            landing_url="https://app.cloudzero.com/explorer",
        )

        self.assertTrue(ok)
        strategy.assert_awaited_once_with(
            context,
            "cloud@example.com",
            "sso@example.com",
            "secret",
            landing_url="https://app.cloudzero.com/explorer",
        )

    async def test_context_strategy_dispatches_with_credentials(self) -> None:
        strategy = AsyncMock(return_value=True)
        context = object()
        dispatcher = LoginDispatcher(
            strategies={
                "atlassian": AuthStrategySpec(
                    func=strategy,
                    target="context",
                    credentials=("atlassian_email", "atlassian_token"),
                )
            }
        )

        ok = await dispatcher.login(
            "atlassian",
            context=context,
            credentials=SimpleNamespace(
                atlassian_email="person@example.com",
                atlassian_token="token",
            ),
        )

        self.assertTrue(ok)
        strategy.assert_awaited_once_with(context, "person@example.com", "token")

    async def test_missing_target_returns_false(self) -> None:
        strategy = AsyncMock(return_value=True)
        dispatcher = LoginDispatcher(
            strategies={
                "sso": AuthStrategySpec(
                    func=strategy,
                    target="page",
                    credentials=("username", "password"),
                )
            }
        )

        ok = await dispatcher.login(
            "sso",
            credentials=AuthCredentials(username="user", password="secret"),
        )

        self.assertFalse(ok)
        strategy.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
