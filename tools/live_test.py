#!/usr/bin/env python3
"""Live end-to-end test of api.py/models.py against a real Automic system.

Only writes to the test row (default ClaudeRoomTest) and restores its values.
All tokens it creates are deleted again.

    AE_PASSWORD=... .venv/bin/python tools/live_test.py
"""

import asyncio
import os
import sys
import types
from datetime import timedelta
from pathlib import Path

import aiohttp

# Import api/models without running the HA-dependent package __init__.
PKG = Path(__file__).resolve().parent.parent / "custom_components" / "automic_heating"
pkg = types.ModuleType("ah")
pkg.__path__ = [str(PKG)]
sys.modules["ah"] = pkg
from ah.api import AutomicClient, format_number  # noqa: E402

URL = os.environ.get("AE_URL", "http://uc4.holli.at:8877")
CLIENT = int(os.environ.get("AE_CLIENT", "1"))
USER = os.environ.get("AE_USER", "HA/HEATING")
PASSWORD = os.environ["AE_PASSWORD"]
ROOM = os.environ.get("AE_TEST_ROOM", "ClaudeRoomTest")
SUMMARY = "HEATING.VARA.ROOM.INFORMATION.SUMMARY"
WEEKDAY = "HEATING.VARA.ROOM.INFORMATION"
WEEKEND = "HEATING.VARA.ROOM.INFORMATION.WEEKEND"


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


async def main():
    async with aiohttp.ClientSession() as session:
        api = AutomicClient(session, URL, CLIENT, USER)
        created = []
        try:
            t1 = await api.create_token(timedelta(hours=1), "HA_BRIDGE_TEST_", PASSWORD)
            created.append(t1.name)
            check(bool(api.token), f"token created via basic auth ({t1.name})")

            summary = await api.get_vara(SUMMARY)
            weekday = await api.get_vara(WEEKDAY)
            weekend = await api.get_vara(WEEKEND)
            check({"actTemp", "HeatingMode", "MustTemp"} <= summary.columns.keys(),
                  f"summary header {summary.columns}")
            check({"Day", "Night", "Mode"} <= weekday.columns.keys(), f"weekday header {weekday.columns}")
            check(ROOM in weekday.rows and ROOM in weekend.rows, f"{ROOM} exists in both settings VARAs")
            print(f"     rooms: {sorted(weekday.rows)}")
            print(f"     {ROOM}: act={summary.number(ROOM, 'actTemp')} must={summary.number(ROOM, 'MustTemp')}"
                  f" wd day/night/mode={weekday.number(ROOM, 'Day')}/{weekday.number(ROOM, 'Night')}/"
                  f"{weekday.integer(ROOM, 'Mode')}")

            # write round trip on both VARAs, then restore
            for vara in (weekday, weekend):
                col = vara.columns["Day"]
                original = vara.raw(ROOM, "Day")
                new = format_number(float(original) + 0.5)
                await api.put_var_col(vara.name, ROOM, col, new)
                after = (await api.get_vara(vara.name)).raw(ROOM, "Day")
                check(after == new, f"{vara.name} {ROOM}._Day {original} -> {after}")
                await api.put_var_col(vara.name, ROOM, col, original)
                restored = (await api.get_vara(vara.name)).raw(ROOM, "Day")
                check(restored == original, f"{vara.name} {ROOM}._Day restored to {restored}")

            # injection guard
            try:
                await api.put_var_col(WEEKDAY, ROOM, 1, '22"\n:PUT_VAR X')
                check(False, "unsafe value rejected")
            except ValueError:
                check(True, "unsafe value rejected")

            # renewal: token creates its successor
            t2 = await api.create_token(timedelta(hours=1), "HA_BRIDGE_TEST_")
            created.append(t2.name)
            check(t2.value != t1.value, "token renewed using current token")
            check((await api.get_vara(SUMMARY)).rows != {}, "new token works")
        finally:
            for name in created:
                await api.delete_token(name)
            print(f"     deleted test tokens: {created}")


asyncio.run(main())
