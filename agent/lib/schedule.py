"""Install/remove a cron job that runs the deterministic pipeline for one scanned folder.

The `crontab` command is injected so tests never touch the real crontab. Each folder gets one
crontab line tagged with a per-folder marker, so installs are idempotent and folders coexist.
Config (folder, schedule, chat webhook) is persisted in `<state>/agent.json`.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess

CONFIG_NAME = "agent.json"
WRAPPER_NAME = "cron-run.sh"
LOG_NAME = "cron.log"


def _marker(state_dir: str) -> str:
    h = hashlib.sha256(os.path.abspath(state_dir).encode()).hexdigest()[:16]
    return f"# drift-detector:{h}"


def config_path(state_dir: str) -> str:
    return os.path.join(state_dir, CONFIG_NAME)


def load_config(state_dir: str) -> dict:
    try:
        with open(config_path(state_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def save_config(state_dir: str, cfg: dict) -> None:
    os.makedirs(state_dir, exist_ok=True)
    with open(config_path(state_dir), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2, sort_keys=True)


def _default_crontab(action: str, content: str | None = None) -> str:
    if action == "read":
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    subprocess.run(["crontab", "-"], input=content or "", text=True, check=True)
    return ""


def _wrapper_script(root: str, state_dir: str, plugin_root: str, chat_webhook: str | None,
                    pull: bool, path_env: str) -> str:
    scan = f'"{plugin_root}/bin/drift-scan" run --root "{root}" --state "{state_dir}" --now "$(date +%F)"'
    if chat_webhook:
        scan += f' --chat-webhook "{chat_webhook}"'
    if pull:
        scan += " --pull"
    log = os.path.join(state_dir, LOG_NAME)
    return ("#!/usr/bin/env bash\n"
            "# drift-detector scheduled run — generated; remove via /drift-detector unschedule\n"
            f'export PATH="{path_env}"\n'
            f'{scan} >> "{log}" 2>&1\n')


def install_cron(root: str, state_dir: str, when: str, *, plugin_root: str,
                 chat_webhook: str | None = None, pull: bool = False,
                 path_env: str | None = None, crontab_run=_default_crontab) -> str:
    """Write the wrapper + install one crontab line. Returns the crontab line for display."""
    root, state_dir = os.path.abspath(root), os.path.abspath(state_dir)
    os.makedirs(state_dir, exist_ok=True)
    path_env = path_env if path_env is not None else os.environ.get("PATH", "/usr/bin:/bin")

    wrapper = os.path.join(state_dir, WRAPPER_NAME)
    with open(wrapper, "w", encoding="utf-8") as fh:
        fh.write(_wrapper_script(root, state_dir, plugin_root, chat_webhook, pull, path_env))
    os.chmod(wrapper, 0o755)

    marker = _marker(state_dir)
    line = f'{when} "{wrapper}"  {marker}'
    existing = [ln for ln in crontab_run("read").splitlines() if marker not in ln and ln.strip()]
    crontab_run("write", "\n".join(existing + [line]) + "\n")

    cfg = load_config(state_dir)
    cfg.update({"root": root, "schedule": when, "pull": pull,
                "connectors": {"chat": {"webhookUrl": chat_webhook}} if chat_webhook else {}})
    save_config(state_dir, cfg)
    return line


def remove_cron(state_dir: str, *, crontab_run=_default_crontab) -> bool:
    """Drop this folder's crontab line. Returns True if a line was removed."""
    marker = _marker(os.path.abspath(state_dir))
    lines = crontab_run("read").splitlines()
    kept = [ln for ln in lines if marker not in ln and ln.strip()]
    crontab_run("write", ("\n".join(kept) + "\n") if kept else "")
    return len(kept) != len([ln for ln in lines if ln.strip()])
