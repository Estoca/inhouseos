"""`iho` command: export, import and snapshot an instance. Reads the same IHO_* settings as the server.

    iho export /backups/move.tar.gz
    iho import /backups/move.tar.gz [--force]
    iho backup-now          one snapshot into IHO_BACKUP_DIR, with the same retention as the schedule

Import into a running server is not supported: stop it, import, start it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from iho.backup import BackupError, BackupScheduler, export_snapshot, import_snapshot
from iho.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iho", description="InHouseOS instance tools")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="write a snapshot of the instance to a .tar.gz")
    exp.add_argument("file", type=Path)
    imp = sub.add_parser("import", help="restore a snapshot into the data dir (server stopped)")
    imp.add_argument("file", type=Path)
    imp.add_argument("--force", action="store_true", help="move the current data aside and restore anyway")
    sub.add_parser("backup-now", help="one snapshot into IHO_BACKUP_DIR, with retention")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        if args.command == "export":
            manifest = export_snapshot(settings, args.file)
        elif args.command == "import":
            manifest = import_snapshot(settings, args.file, force=args.force)
        else:
            scheduler = BackupScheduler(settings)
            if not scheduler.enabled:
                print("IHO_BACKUP_DIR is not set.", file=sys.stderr)
                return 2
            scheduler.run_once()
            print(json.dumps(scheduler.last, indent=2))
            return 0
    except (BackupError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"created_at": manifest["created_at"], "repos": len(manifest["repos"]),
                      "db": bool(manifest["db"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
