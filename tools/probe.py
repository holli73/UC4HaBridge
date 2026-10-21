#!/usr/bin/env python3
"""Read-only probe of the Automic 24.4 REST API, used to shape the HA integration.

Reads config from ../.env, makes NO writes to any VARA, and dumps raw responses to
probe_out/ so the JSON layout (object counter, VARA rows, script output) can be inspected.

    python3 tools/probe.py
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "probe_out"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
BASE = f"{ENV['AE_URL'].rstrip('/')}/{ENV['AE_CLIENT']}"
CTX = None if ENV.get("AE_VERIFY_TLS", "true").lower() == "true" else ssl._create_unverified_context()


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": ENV["AE_AUTH"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            raw = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode(), e.code
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        data = raw
    return status, data


def dump(name, status, data):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps({"status": status, "body": data}, indent=2))
    preview = json.dumps(data)[:300] if not isinstance(data, str) else data[:300]
    print(f"[{status}] {name}: {preview}")


def main():
    varas = [ENV[k] for k in ("AE_VARA_ACTUAL", "AE_VARA_TARGET", "AE_VARA_MODE",
                               "AE_VARA_WEEKDAY", "AE_VARA_WEEKEND")]

    # 1. Object export: shows VARA rows (header row 1) and object metadata/counters.
    for v in varas:
        dump(f"object_{v}", *call("GET", f"/objects/{v}"))

    # 2. Inline script (read-only): print one VARA row via the scripts endpoint.
    room, vara = ENV["AE_TEST_ROOM"], ENV["AE_VARA_TARGET"]
    script = (
        f':SET &V1# = GET_VAR("{vara}", "{room}", 1)\n'
        f':PRINT "HA_PROBE|{room}|&V1#"\n'
    )
    status, data = call("POST", "/scripts", {"script": script})
    dump("script_post", status, data)

    # 3. Fetch the script's report if a run_id came back.
    run_id = data.get("run_id") if isinstance(data, dict) else None
    if run_id:
        time.sleep(2)
        dump("script_execution", *call("GET", f"/executions/{run_id}"))
        for rep in ("REP", "ACT", "LOG"):
            dump(f"script_report_{rep}", *call("GET", f"/executions/{run_id}/reports/{rep}"))

    print(f"\nRaw responses written to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
