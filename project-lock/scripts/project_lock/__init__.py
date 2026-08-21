"""Cooperative project locking for coding agents."""

from .core import (
    OWNER_PID_ENVIRONMENT_VARIABLES,
    SESSION_ID_ENVIRONMENT_VARIABLES,
    LockConflict,
    LockOwnershipError,
    acquire,
    governing_lock,
    has_git_ancestor,
    inspect,
    is_under_temp_dir,
    list_locks,
    nearest_worktree_root,
    related_locks,
    release,
    renew,
)

__all__ = [
    "OWNER_PID_ENVIRONMENT_VARIABLES",
    "SESSION_ID_ENVIRONMENT_VARIABLES",
    "LockConflict",
    "LockOwnershipError",
    "acquire",
    "governing_lock",
    "has_git_ancestor",
    "inspect",
    "is_under_temp_dir",
    "list_locks",
    "nearest_worktree_root",
    "related_locks",
    "release",
    "renew",
]
