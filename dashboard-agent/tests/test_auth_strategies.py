import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth import registry
from src.auth.config import AuthStrategySpec


class ExecuteAuthStrategyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_registry = dict(registry.AUTH_STRATEGIES)

    def tearDown(self) -> None:
        registry.AUTH_STRATEGIES.clear()
        registry.AUTH_STRATEGIES.update(self._original_registry)

    async def test_unknown_auth_type_returns_false(self) -> None:
        page = object()
        context = object()
        creds = SimpleNamespace()

        ok = await registry.execute_auth_strategy("does-not-exist", page, context, creds)

        self.assertFalse(ok)

    async def test_optional_strategy_skips_when_credentials_missing(self) -> None:
        fake_strategy = AsyncMock(return_value=True)
        registry.AUTH_STRATEGIES.clear()
        registry.AUTH_STRATEGIES["cloudhealth"] = AuthStrategySpec(
            func=fake_strategy,
            requires_page=False,
            credentials=("cloudhealth_email",),
            skip_if_missing="skip",
        )

        page = object()
        context = object()
        creds = SimpleNamespace(cloudhealth_email="")

        ok = await registry.execute_auth_strategy("cloudhealth", page, context, creds)

        self.assertTrue(ok)
        fake_strategy.assert_not_awaited()

    async def test_page_strategy_dispatches_with_credentials(self) -> None:
        fake_strategy = AsyncMock(return_value=True)
        registry.AUTH_STRATEGIES.clear()
        registry.AUTH_STRATEGIES["sso"] = AuthStrategySpec(
            func=fake_strategy,
            requires_page=True,
            credentials=("username", "password"),
        )

        page = object()
        context = object()
        creds = SimpleNamespace(username="user", password="secret")

        ok = await registry.execute_auth_strategy("sso", page, context, creds)

        self.assertTrue(ok)
        fake_strategy.assert_awaited_once_with(page, "user", "secret")

    async def test_context_strategy_dispatches_with_credentials(self) -> None:
        fake_strategy = AsyncMock(return_value=True)
        registry.AUTH_STRATEGIES.clear()
        registry.AUTH_STRATEGIES["atlassian"] = AuthStrategySpec(
            func=fake_strategy,
            requires_page=False,
            credentials=("atlassian_email", "atlassian_token"),
            skip_if_missing="skip",
        )

        page = object()
        context = object()
        creds = SimpleNamespace(atlassian_email="a@corp.com", atlassian_token="token")

        ok = await registry.execute_auth_strategy("atlassian", page, context, creds)

        self.assertTrue(ok)
        fake_strategy.assert_awaited_once_with(context, "a@corp.com", "token")


if __name__ == "__main__":
    unittest.main()
