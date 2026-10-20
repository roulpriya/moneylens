#!/usr/bin/env python3
"""Nonsecret setup configuration, daily scan checkpoints, and retry bookkeeping."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid
from zoneinfo import ZoneInfo
from ledger import connect, date, default_dir, hash_value, require, text


def get(db, key, default=None):
    row = db.execute("SELECT value FROM runtime_meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db, key, value):
    db.execute("INSERT OR REPLACE INTO runtime_meta VALUES (?,?)", (key, json.dumps(value)))


def now():
    return dt.datetime.now(dt.timezone.utc)


def config_validated(p):
    allowed = {"mailbox", "gmail_verified_at", "initial_start", "timezone", "daily_time", "cards",
               "confirmed_card_count", "report_path", "automation_id", "auto_save_validated", "discovery_notes"}
    require(isinstance(p, dict) and not (set(p) - allowed), "Unexpected setup fields; credentials never belong in setup JSON")
    p = json.loads(json.dumps(p))
    for key in ("mailbox", "gmail_verified_at", "timezone", "daily_time", "report_path"):
        p[key] = text(p.get(key), key, 2000)
    dt.datetime.fromisoformat(p["gmail_verified_at"])
    ZoneInfo(p["timezone"])
    require(bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", p["daily_time"])), "daily_time must be HH:MM")
    date(p.get("initial_start"))
    require(Path(p["report_path"]).is_absolute() and p["report_path"].endswith(".html"), "report_path must be an absolute HTML path")
    require(p.get("auto_save_validated") is True, "This workflow requires the confirmed automatic-save policy")
    require(isinstance(p.get("cards"), list) and p["cards"], "At least one identified card is required")
    keys = []
    for card in p["cards"]:
        require(isinstance(card, dict) and not (set(card) - {"account_key", "issuer", "last4", "keychain_scope", "password_status", "verified_at"}), "Unexpected card fields")
        for key in ("account_key", "issuer", "last4", "keychain_scope", "password_status"):
            card[key] = text(card.get(key), key)
        require(bool(re.fullmatch(r"\d{4}", card["last4"])), "Only last four card digits belong in setup")
        require(card["password_status"] in {"verified", "not_required", "unverified"}, "Invalid password status")
        if card["password_status"] == "verified":
            dt.datetime.fromisoformat(card.get("verified_at", ""))
        keys.append(card["account_key"])
    require(len(set(keys)) == len(keys), "Card list contains duplicate account identities")
    require(type(p.get("confirmed_card_count")) is int and p["confirmed_card_count"] == len(keys), "User-confirmed card count must match the inventory")
    p["ready"] = all(c["password_status"] in {"verified", "not_required"} for c in p["cards"])
    return p


def retries(db):
    return [json.loads(row[0]) for row in db.execute("SELECT payload FROM retry_sources ORDER BY source_key")]


def begin(db):
    config = get(db, "config")
    require(config and config["ready"], "Run moneylens-setup to confirm cards and verify required passwords first")
    current = now()
    active = get(db, "active_run")
    require(not active or dt.datetime.fromisoformat(active["expires_at"]) < current, "Another daily run holds the sync lease")
    run = {"id": uuid.uuid4().hex, "started_at": current.isoformat(), "expires_at": (current + dt.timedelta(hours=2)).isoformat()}
    put(db, "active_run", run)
    last = get(db, "last_success")
    start = (dt.datetime.fromisoformat(last) - dt.timedelta(days=3)).date().isoformat() if last else config["initial_start"]
    return {"run": run, "config": config, "search_from": start, "search_before": (current + dt.timedelta(days=1)).date().isoformat(), "retry_sources": retries(db)}


def finish(db, run_id, search_complete, error):
    active = get(db, "active_run")
    require(active and active["id"] == run_id, "Run lease not found or owned by another run")
    success = bool(search_complete and not error)
    if success:
        put(db, "last_success", active["started_at"])
    put(db, "last_run", {"started_at": active["started_at"], "finished_at": now().isoformat(), "success": success,
                         "error": error, "pending_sources": len(retries(db))})
    db.execute("DELETE FROM runtime_meta WHERE key='active_run'")
    return {"result": "scan_completed" if success else "scan_incomplete", "cursor_advanced": success, "retry_sources": len(retries(db))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_dir())
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("configure")
    p.add_argument("--input", type=Path, required=True)
    sub.add_parser("status")
    sub.add_parser("begin-run")
    p = sub.add_parser("finish-run")
    p.add_argument("--run-id", required=True)
    p.add_argument("--search-complete", action="store_true")
    p.add_argument("--error", default="")
    p = sub.add_parser("set-automation")
    p.add_argument("--id", required=True)
    p = sub.add_parser("retry-add")
    p.add_argument("--message", required=True)
    p.add_argument("--attachment", default="")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("retry-remove")
    p.add_argument("--key", required=True)
    args = parser.parse_args()
    db = connect(args.data_dir)
    try:
        db.execute("BEGIN IMMEDIATE")
        if args.command == "configure":
            require(args.input.stat().st_size <= 1024 * 1024, "Setup input too large")
            p = config_validated(json.loads(args.input.read_text()))
            old = get(db, "config", {})
            require(not old or old["mailbox"] == p["mailbox"], "Use a separate data directory for a different mailbox")
            if old.get("automation_id") and not p.get("automation_id"):
                p["automation_id"] = old["automation_id"]
            put(db, "config", p)
            result = {"result": "configured", "ready": p["ready"], "cards": len(p["cards"])}
        elif args.command == "status":
            result = {"config": get(db, "config"), "last_success": get(db, "last_success"), "last_run": get(db, "last_run"), "retry_sources": retries(db)}
        elif args.command == "begin-run":
            result = begin(db)
        elif args.command == "finish-run":
            result = finish(db, args.run_id, args.search_complete, args.error)
        elif args.command == "set-automation":
            p = get(db, "config")
            require(p and p["ready"], "Setup must be ready before saving an automation ID")
            p["automation_id"] = text(args.id, "automation ID")
            put(db, "config", p)
            result = {"result": "automation_linked"}
        elif args.command == "retry-add":
            p = {"message_id": text(args.message, "message ID"), "attachment_id": args.attachment,
                 "reason": text(args.reason, "retry reason", 1000), "updated_at": now().isoformat()}
            key = hash_value([p["message_id"], p["attachment_id"]])[:24]
            p["key"] = key
            db.execute("INSERT OR REPLACE INTO retry_sources VALUES (?,?)", (key, json.dumps(p)))
            result = {"result": "queued", "key": key}
        else:
            db.execute("DELETE FROM retry_sources WHERE source_key=?", (args.key,))
            result = {"result": "retry_resolved"}
        db.commit()
        print(json.dumps(result))
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
