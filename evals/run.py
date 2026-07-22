"""Run the retrieval eval and print a scorecard.

    uv run python -m evals.run                 # shipped setting only
    uv run python -m evals.run --sweep         # also try larger top-n
    uv run python -m evals.run --min-recall 0.9

Exits non-zero when recall at the shipped ``cfg.retrieval_n`` falls below
``--min-recall``, so this can gate a change that quietly makes retrieval worse.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from autofill.agent import cfg

from . import retrieval
from .cases import fixtures

console = Console()

SWEEP = [5, 10, 20, 40]


def _scorecard(scored: dict[str, list[retrieval.Result]], n: int) -> None:
    table = Table(title=f"Fact recall at top-{n}", title_justify="left")
    table.add_column("Profile")
    table.add_column("Facts", justify="right")
    table.add_column("Found", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("Lost to ranking", justify="right")
    table.add_column("Lost to chunking", justify="right")

    for fixture, results in scored.items():
        counts = retrieval.tally(results)
        table.add_row(
            fixture,
            str(len(results)),
            str(counts[retrieval.OK]),
            f"{retrieval.recall(results):.0%}",
            str(counts[retrieval.NOT_RANKED]),
            str(counts[retrieval.SPLIT]),
        )
    console.print(table)


def _misses(scored: dict[str, list[retrieval.Result]]) -> None:
    rows = [
        (fixture, result)
        for fixture, results in scored.items()
        for result in results
        if result.status != retrieval.OK
    ]
    if not rows:
        console.print("[green]No missing facts.[/]")
        return

    table = Table(title="Missing facts", title_justify="left")
    table.add_column("Profile")
    table.add_column("Field a form would ask for")
    table.add_column("Why")
    for fixture, result in rows:
        why = (
            "chunk was not in top-n"
            if result.status == retrieval.NOT_RANKED
            else "fact split across chunks"
        )
        table.add_row(fixture, result.case.field, why)
    console.print(table)


def _sweep(per_fixture: dict[str, dict[int, list[retrieval.Result]]]) -> None:
    table = Table(title="Recall as top-n grows", title_justify="left")
    table.add_column("Profile")
    for n in SWEEP:
        table.add_column(f"n={n}", justify="right")
    for fixture, by_n in per_fixture.items():
        table.add_row(
            fixture, *[f"{retrieval.recall(by_n[n]):.0%}" for n in SWEEP]
        )
    console.print(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="also report recall at larger top-n values",
    )
    parser.add_argument(
        "--min-recall",
        type=float,
        default=0.0,
        help="exit non-zero if recall at the shipped top-n is below this",
    )
    args = parser.parse_args(argv)

    shipped = cfg.retrieval_n
    ns = sorted({shipped, *SWEEP}) if args.sweep else [shipped]

    per_fixture = {name: retrieval.run(name, ns) for name in fixtures()}
    at_shipped = {name: by_n[shipped] for name, by_n in per_fixture.items()}

    _scorecard(at_shipped, shipped)
    _misses(at_shipped)
    if args.sweep:
        _sweep(per_fixture)

    every = [result for results in at_shipped.values() for result in results]
    overall = retrieval.recall(every)
    console.print(f"\nOverall recall at top-{shipped}: [bold]{overall:.0%}[/]")

    if overall < args.min_recall:
        console.print(
            f"[red]Below the {args.min_recall:.0%} floor.[/]"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
