from __future__ import annotations

import argparse

from src import trader


def run_scheduled_cycle(mode: str = "execute") -> dict:
    return trader.run(mode=mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seven Split scheduled trading runner")
    parser.add_argument(
        "--mode",
        choices=["execute", "analysis_only"],
        default="execute",
        help="execute orders immediately when policy allows, or queue analysis output only",
    )
    args = parser.parse_args()
    run_scheduled_cycle(mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
