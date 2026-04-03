import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class Credentials:
    email: str           # TABLEAU_EMAIL
    username: str        # SSO_USERNAME (internal SSO username)
    password: str        # SSO_PASSWORD
    atlassian_email: str = ""    # ATLASSIAN_EMAIL
    atlassian_token: str = ""    # ATLASSIAN_API_TOKEN
    cloudhealth_email: str = ""  # CLOUDHEALTH_EMAIL
    cloudzero_email: str = ""    # CLOUDZERO_EMAIL


def load_credentials(env_path: str | None = None) -> Credentials:
    # .env lives at dashboard-agent/.env
    resolved_path = Path(env_path) if env_path else Path(__file__).resolve().parents[2] / ".env"
    if not resolved_path.exists():
        raise FileNotFoundError(
            f".env file not found at {resolved_path}. "
            f"Copy .env.example to {resolved_path} and fill in your credentials."
        )
    load_dotenv(str(resolved_path))

    email = os.environ.get("TABLEAU_EMAIL", "")
    username = os.environ.get("SSO_USERNAME", "")
    password = os.environ.get("SSO_PASSWORD", "")

    if not all([email, username, password]):
        missing = [k for k, v in {"TABLEAU_EMAIL": email, "SSO_USERNAME": username, "SSO_PASSWORD": password}.items() if not v]
        raise EnvironmentError(
            f"Missing env vars: {', '.join(missing)} in {resolved_path}. "
            f"Refer to .env.example for required keys."
        )

    return Credentials(
        email=email,
        username=username,
        password=password,
        atlassian_email=os.environ.get("ATLASSIAN_EMAIL", ""),
        atlassian_token=os.environ.get("ATLASSIAN_API_TOKEN", ""),
        cloudhealth_email=os.environ.get("CLOUDHEALTH_EMAIL", ""),
        cloudzero_email=os.environ.get("CLOUDZERO_EMAIL", ""),
    )
