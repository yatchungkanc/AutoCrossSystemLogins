# Auth Package Overview

This package is split by concern to keep authentication logic easy to extend and maintain.

## Module Responsibilities

- `config.py`
  - Holds auth configuration dataclasses and provider-specific config constants.
- `common.py`
  - Shared login helpers used across providers (Microsoft SSO flow, generic email login flow).
- `ms_sso_services.py`
  - Provider logins that use Microsoft SSO-style authentication (Tableau, SSO, AI Pro).
- `email_sso_services.py`
  - Provider logins that begin with email submission and may continue through SSO redirects (CloudHealth, CloudZero, Atlassian).
- `registry.py`
  - Strategy registry and `execute_auth_strategy()` dispatch function.
- `__init__.py`
  - Package-level public API export for `execute_auth_strategy()`.

## Import Guidance

- Preferred orchestrator import:
  - `from auth import execute_auth_strategy`
- For tests or lower-level extension points:
  - Import strategy metadata and registry from `auth.config` and `auth.registry`.
- `auth.strategies` remains a minimal compatibility facade and should not be used for new imports.
