"""Small typed models returned by the GitHub service layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RateLimitSnapshot:
    limit: int | None = None
    remaining: int | None = None
    used: int | None = None
    reset_epoch: int | None = None
    resource: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    login: str
    user_id: int
    account_type: str
    name: str | None
    html_url: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
