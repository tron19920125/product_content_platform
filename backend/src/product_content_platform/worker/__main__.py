from __future__ import annotations

import argparse
import time

from product_content_platform.api.app import app


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover and process persisted local production jobs")
    parser.add_argument("--once", action="store_true", help="Process queued jobs once and exit")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    production = app.state.production
    while True:
        production.recover_pending()
        if args.once:
            return 0
        time.sleep(max(.5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
