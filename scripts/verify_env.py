"""Print the CodeAtlas tool matrix and exit nonzero if the target milestone's tools are missing.

Usage: python scripts/verify_env.py [--through M4]
"""

from __future__ import annotations

import argparse
import sys

from codeatlas.core.toolcheck import build_matrix, format_matrix, matrix_exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--through",
        default="M0",
        help="fail (exit 1) if a tool required by milestones up to this one is missing",
    )
    args = parser.parse_args(argv)

    statuses = build_matrix()
    print(format_matrix(statuses))
    code = matrix_exit_code(statuses, through_milestone=args.through)
    if code != 0:
        print(f"\nFAIL: missing tools required through {args.through}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
