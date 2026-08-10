"""Sweep the recording corpus through readonly replay.

Takes a directory of recordings (default ``artifacts/``), distils each one
through ``distil_readonly``, compiles to a scenario, runs it, and emits a
summary with PASS/FAIL/REFUSED counts. Designed to be run from the CLI or
imported.

Usage::

    python3 -m oaflow.corpus_sweep              # default: artifacts/
    python3 -m oaflow.corpus_sweep /path/to/dir  # custom directory

If any plan had ``deps_checked=False`` (because the DB tunnel was down when
entity existence was checked), the summary warns that REFUSED counts may be
unreliable.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .replay import Plan, StaleRecording, distil_readonly, run
from .scenario import ScenarioError


@dataclass
class SweepEntry:
    name: str
    verdict: str  # PASS | FAIL | REFUSED | ERROR
    detail: str = ""
    deps_checked: bool = True
    elapsed_s: float = 0.0


@dataclass
class SweepResult:
    entries: list[SweepEntry] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def pass_count(self) -> int:
        return sum(1 for e in self.entries if e.verdict == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for e in self.entries if e.verdict == "FAIL")

    @property
    def refused_count(self) -> int:
        return sum(1 for e in self.entries if e.verdict == "REFUSED")

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.entries if e.verdict == "ERROR")

    @property
    def unchecked_count(self) -> int:
        return sum(1 for e in self.entries if not e.deps_checked)

    def summary_lines(self) -> list[str]:
        total = len(self.entries)
        lines = [
            f"Sweep completed in {self.elapsed_s:.0f}s",
            "",
            f"PASS:    {self.pass_count}",
            f"FAIL:    {self.fail_count}",
            f"REFUSED: {self.refused_count}",
        ]
        if self.error_count:
            lines.append(f"ERROR:   {self.error_count}")

        if self.unchecked_count:
            lines.append("")
            lines.append(
                f"WARNING: entity existence unverified for "
                f"{self.unchecked_count} of {total} plans - "
                f"REFUSED counts are unreliable"
            )

        if self.fail_count:
            lines.append("")
            lines.append("=== FAILs ===")
            for e in self.entries:
                if e.verdict == "FAIL":
                    lines.append(f"{e.name}: {e.detail}")

        if self.refused_count:
            lines.append("")
            lines.append("=== REFUSED (sample) ===")
            refused = [e for e in self.entries if e.verdict == "REFUSED"]
            for e in refused[:5]:
                lines.append(f"{e.name}: {e.detail}")
            if len(refused) > 5:
                lines.append(f"  ... and {len(refused) - 5} more")

        return lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_count,
            "fail": self.fail_count,
            "refused": self.refused_count,
            "error": self.error_count,
            "unchecked": self.unchecked_count,
            "elapsed_s": round(self.elapsed_s),
            "entries": [
                {
                    "name": e.name,
                    "verdict": e.verdict,
                    "detail": e.detail,
                    "deps_checked": e.deps_checked,
                }
                for e in self.entries
            ],
        }


def sweep(
    recordings_dir: Path | None = None,
    env: str = config.DEFAULT_ENV,
    progress=lambda m: sys.stdout.write(m + "\n") or sys.stdout.flush(),
) -> SweepResult:
    """Run the readonly corpus sweep.

    Iterates over every subdirectory in ``recordings_dir`` that contains a
    ``recording.jsonl`` file, distils it, compiles to a scenario, and runs it.
    """
    root = recordings_dir or config.ARTIFACTS_DIR
    recordings = sorted(
        p for p in root.iterdir()
        if p.is_dir() and (p / "recording.jsonl").exists()
    )

    result = SweepResult()
    t0 = time.monotonic()
    total = len(recordings)

    for idx, rec_dir in enumerate(recordings, 1):
        rec_name = rec_dir.name
        rec_file = rec_dir / "recording.jsonl"
        progress(f"  [{idx}/{total}] {rec_name}")

        t_start = time.monotonic()
        try:
            plan = distil_readonly(rec_file, env=env)
            if not plan.calls:
                result.entries.append(SweepEntry(
                    name=rec_name,
                    verdict="REFUSED",
                    detail="no replayable calls (no QueryExplore/LoadExplore)",
                    elapsed_s=time.monotonic() - t_start,
                ))
                continue

            scenario = plan.to_scenario(f"S-{rec_name}", check_deps=True)
            report = run(plan, ident=f"S-{rec_name}", check_deps=False)

            entry = SweepEntry(
                name=rec_name,
                verdict=report.verdict,
                detail=report.error or "",
                deps_checked=plan.deps_checked,
                elapsed_s=time.monotonic() - t_start,
            )
            if report.verdict == "FAIL" and not report.error:
                failed = report.failed_steps
                if failed:
                    entry.detail = (
                        f"StepFailed: step {failed[0].index} "
                        f"'{failed[0].name}' failed its assertions"
                    )
            result.entries.append(entry)

        except StaleRecording as e:
            result.entries.append(SweepEntry(
                name=rec_name,
                verdict="REFUSED",
                detail=str(e),
                elapsed_s=time.monotonic() - t_start,
            ))
        except ScenarioError as e:
            result.entries.append(SweepEntry(
                name=rec_name,
                verdict="REFUSED",
                detail=str(e),
                elapsed_s=time.monotonic() - t_start,
            ))
        except Exception as e:
            result.entries.append(SweepEntry(
                name=rec_name,
                verdict="ERROR",
                detail=f"{type(e).__name__}: {e}",
                elapsed_s=time.monotonic() - t_start,
            ))

    result.elapsed_s = time.monotonic() - t0
    return result


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Sweep the recording corpus through readonly replay."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=str(config.ARTIFACTS_DIR),
        help="Directory containing recording subdirectories (default: artifacts/)",
    )
    parser.add_argument(
        "--env",
        default=config.DEFAULT_ENV,
        help=f"Target environment (default: {config.DEFAULT_ENV})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args(argv)

    result = sweep(
        recordings_dir=Path(args.directory),
        env=args.env,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        for line in result.summary_lines():
            print(line)


if __name__ == "__main__":
    main()
