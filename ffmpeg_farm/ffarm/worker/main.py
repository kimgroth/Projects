"""
CLI entry point for worker process.
"""

from __future__ import annotations

import argparse
import logging

from .client import WorkerClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FFarm worker node")
    parser.add_argument("--master", default="http://127.0.0.1:8000", help="Master base URL")
    parser.add_argument("--id", dest="worker_id", help="Worker ID (defaults to random UUID)")
    parser.add_argument("--name", help="Friendly worker name")
    parser.add_argument("--no-zeroconf", dest="advertise", action="store_false", help="Disable Zeroconf advertisement")
    parser.set_defaults(advertise=True)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
    worker = WorkerClient(
        args.master,
        worker_id=args.worker_id,
        name=args.name,
        advertise=args.advertise,
    )
    try:
        worker.run()
    except KeyboardInterrupt:
        worker.stop()


if __name__ == "__main__":
    main()
