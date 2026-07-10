"""Commit report + state files to the reports repo (the only GitLab write path)."""
from __future__ import annotations


def commit_files(client, project_id: int, branch: str, message: str, files: dict, ref: str) -> str:
    actions = []
    for path, content in files.items():
        action = "update" if client.get_raw_file(project_id, path, ref) is not None else "create"
        actions.append({"action": action, "file_path": path, "content": content})
    return client.create_commit(project_id, branch, message, actions)["id"]
