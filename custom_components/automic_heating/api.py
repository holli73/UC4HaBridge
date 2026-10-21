"""Async client for the Automic Automation Engine REST API (v1). No HA imports.

Reads use the object export (GET /objects/{name}); writes run an inline AE script
via POST /scripts containing :PUT_VAR_COL, so no helper objects exist in Automic.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import aiohttp

from .models import Vara

STATUS_ENDED_OK = 1900
STATUS_ENDED_MIN = 1800  # every status >= 1800 is a final state
SCRIPT_TIMEOUT = 20  # seconds to wait for an inline script to finish

# Everything interpolated into an AE script must match one of these.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.$@#\-]+$")
_SAFE_VALUE = re.compile(r"^-?\d+(\.\d+)?$")


class AutomicError(Exception):
    """Generic API failure."""


class AutomicAuthError(AutomicError):
    """Credentials or token rejected (HTTP 401)."""


@dataclass
class Token:
    name: str
    value: str
    expires: datetime


class AutomicClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        client: int,
        user: str,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._base = f"{url.rstrip('/')}/ae/api/v1/{client}"
        self._client = client
        self._user = user
        self._token = token

    @property
    def token(self) -> str | None:
        return self._token

    # ---- low level -------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        auth: aiohttp.BasicAuth | None = None,
        ok: tuple[int, ...] = (200,),
    ) -> Any:
        headers = {"Accept": "application/json"}
        if auth is None:
            if not self._token:
                raise AutomicAuthError("No API token configured")
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with self._session.request(
                method,
                self._base + path,
                json=json,
                auth=auth,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    raise AutomicAuthError(f"{method} {path}: unauthorized")
                if resp.status not in ok:
                    raise AutomicError(
                        f"{method} {path}: HTTP {resp.status} {await resp.text()}"
                    )
                if resp.content_length == 0:
                    return None
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AutomicError(f"{method} {path}: {err}") from err

    # ---- tokens ----------------------------------------------------------

    def _tokens_path(self) -> str:
        return f"/system/users/{quote(self._user, safe='')}/tokens"

    async def create_token(
        self, lifetime: timedelta, prefix: str, password: str | None = None
    ) -> Token:
        """Create a new API token.

        With a password, basic auth is used (initial setup / reauth); otherwise
        the current token creates its own successor.
        """
        expires = (datetime.now(timezone.utc) + lifetime).replace(microsecond=0)
        name = f"{prefix}{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
        auth = aiohttp.BasicAuth(self._user, password, "latin-1") if password else None
        data = await self._request(
            "POST",
            self._tokens_path(),
            json={
                "token_name": name,
                "expiration_date": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            auth=auth,
        )
        value = (data or {}).get("token")
        if not value:
            raise AutomicError(f"Token creation returned no token: {data}")
        self._token = value
        return Token(name, value, expires)

    async def delete_token(self, name: str) -> None:
        """Best effort: AE 24.4 deletes the token but may still answer 400."""
        await self._request(
            "DELETE",
            f"{self._tokens_path()}/{quote(name, safe='')}?target_client={self._client}",
            ok=(200, 204, 400),
        )

    # ---- reads -----------------------------------------------------------

    async def get_vara(self, name: str) -> Vara:
        return Vara.from_export(name, await self._request("GET", f"/objects/{quote(name)}"))

    # ---- writes ----------------------------------------------------------

    async def run_script(self, script: str) -> int:
        """Run an inline AE script and wait until it ends. Returns the run id."""
        data = await self._request("POST", "/scripts", json={"script": script})
        run_id = data["run_id"]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SCRIPT_TIMEOUT
        while True:
            execution = await self._request("GET", f"/executions/{run_id}")
            status = int(execution.get("status", 0))
            if status >= STATUS_ENDED_MIN:
                if status != STATUS_ENDED_OK:
                    raise AutomicError(
                        f"Script {run_id} failed: {execution.get('status_text')}"
                    )
                return run_id
            if loop.time() > deadline:
                raise AutomicError(f"Script {run_id} did not finish in time")
            await asyncio.sleep(0.5)

    async def put_var_col(self, vara: str, key: str, column: int, value: str) -> None:
        """Write a single VARA cell via an inline :PUT_VAR_COL script."""
        if not (_SAFE_NAME.match(vara) and _SAFE_NAME.match(key)):
            raise ValueError(f"Unsafe VARA name or key: {vara!r} / {key!r}")
        if not _SAFE_VALUE.match(value) or not 1 <= column <= 5:
            raise ValueError(f"Unsafe value or column: {value!r} / {column}")
        await self.run_script(f':PUT_VAR_COL {vara}, "{key}", {column}, "{value}"')


def format_number(value: float) -> str:
    """22.0 -> "22", 22.5 -> "22.5" (matches how the VARAs are maintained)."""
    return f"{round(value, 1):g}"
