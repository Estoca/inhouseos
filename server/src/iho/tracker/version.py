"""Version reported by the tracker code: the iho-server's."""
import os

from iho import __version__


def git_commit() -> str:
    return os.environ.get("GIT_COMMIT_SHA", "unknown")


def app_version() -> str:
    return __version__
