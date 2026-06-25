"""Container health check.

The running bot refreshes HEARTBEAT_FILE every few seconds (see main.py).
This script — run by Docker's HEALTHCHECK — exits 0 only if that file is
fresh, which means the bot's event loop is alive (not just the process).
"""

import os
import sys
import time

HEARTBEAT_FILE = "/tmp/bot_heartbeat"
MAX_AGE_SECONDS = 90


def main() -> int:
    try:
        age = time.time() - os.path.getmtime(HEARTBEAT_FILE)
    except OSError:
        print("no heartbeat file yet", file=sys.stderr)
        return 1
    if age > MAX_AGE_SECONDS:
        print(f"heartbeat stale ({age:.0f}s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
