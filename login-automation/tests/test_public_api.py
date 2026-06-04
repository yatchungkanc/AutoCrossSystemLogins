import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class PublicApiTests(unittest.TestCase):
    def test_imports_public_wrappers(self) -> None:
        import autocross_login

        self.assertTrue(callable(autocross_login.login))
        self.assertTrue(callable(autocross_login.login_powerbi))
        self.assertTrue(callable(autocross_login.login_cloudzero))
        self.assertTrue(callable(autocross_login.login_atlassian))


if __name__ == "__main__":
    unittest.main()
