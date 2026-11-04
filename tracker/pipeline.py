"""CLI entry point: python -m tracker.pipeline [--sources npm,pypi,hn,github,sec] [--full]

Each source runs independently; a failure in one is logged to
data/run_log.json and doesn't stop the others. Exit code is non-zero if any
step failed, so the GitHub Actions run shows red (after data is committed).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import traceback

from tracker.config import DATA

ALL = ["npm", "pypi", "hn", "github", "sec"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=",".join(ALL))
    ap.add_argument("--full", action="store_true", help="refetch full history")
    ap.add_argument("--skip-fetch", action="store_true", help="only rebuild + analyze")
    ap.add_argument("--no-analysis", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    log = {"started": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z", "steps": {}}
    sources = [] if args.skip_fetch else [s.strip() for s in args.sources.split(",") if s.strip()]

    def step(name, fn):
        try:
            res = fn()
            n = len(res) if hasattr(res, "__len__") else None
            log["steps"][name] = {"ok": True, "rows": n}
        except Exception as exc:
            logging.error("%s failed: %s", name, exc)
            traceback.print_exc()
            log["steps"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}

    if "npm" in sources:
        from tracker.fetch import npm
        step("npm", lambda: npm.run(full=args.full))
    if "pypi" in sources:
        from tracker.fetch import pypi
        step("pypi", pypi.run)
    if "hn" in sources:
        from tracker.fetch import hn
        step("hn", lambda: hn.run(full=args.full))
    if "github" in sources:
        from tracker.fetch import github
        step("github", github.run)
    if "sec" in sources:
        from tracker.fetch import sec
        step("sec", sec.run)

    from tracker import build
    outs = {}

    def _build():
        outs.update(build.run())
        return outs
    step("build", _build)

    if not args.no_analysis:
        from tracker.analysis import leadlag
        step("leadlag", lambda: leadlag.run() or [])

    from tracker import summary
    step("summary", lambda: [summary.generate(outs.get("what_moved"))])

    log["finished"] = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
    (DATA / "run_log.json").write_text(json.dumps(log, indent=2))
    failed = [k for k, v in log["steps"].items() if not v["ok"]]
    if failed:
        logging.error("failed steps: %s", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
