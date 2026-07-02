#!/usr/bin/env python3
"""Group Vivado report_timing paths by structural fingerprints."""

from __future__ import annotations

import argparse
import collections
import dataclasses
import re
import statistics
from pathlib import Path


FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"


@dataclasses.dataclass
class TimingPath:
    index: int
    slack: float
    source: str = ""
    destination: str = ""
    path_group: str = ""
    data_delay: float | None = None
    logic_delay: float | None = None
    route_delay: float | None = None
    logic_levels: int | None = None
    start_line: int = 0


def strip_cell_pin(name: str) -> str:
    name = name.strip()
    if "/" in name:
        return name.rsplit("/", 1)[0]
    return name


def normalize_name(name: str) -> str:
    name = strip_cell_pin(name)
    name = re.sub(r"\[[^\]]+\]", "[]", name)
    name = re.sub(r"__\d+", "__N", name)
    name = re.sub(r"_replica(?:_\d+)?", "_replica_N", name)
    name = re.sub(r"_i_\d+", "_i_N", name)
    name = re.sub(r"_reg_\d+", "_reg_N", name)
    return name


def module_head(name: str, depth: int) -> str:
    cell = strip_cell_pin(name)
    parent = cell.rsplit("/", 1)[0] if "/" in cell else cell
    parts = parent.split("/")
    if len(parts) <= depth:
        return parent
    return "/".join(parts[:depth])


def parse_report(path: Path) -> list[TimingPath]:
    paths: list[TimingPath] = []
    current: TimingPath | None = None
    slack_re = re.compile(rf"^Slack \([^)]*\)\s*:\s*({FLOAT_RE})ns")
    source_re = re.compile(r"^\s*Source:\s*(\S+)")
    dest_re = re.compile(r"^\s*Destination:\s*(\S+)")
    group_re = re.compile(r"^\s*Path Group:\s*(\S+)")
    delay_re = re.compile(
        rf"^\s*Data Path Delay:\s*({FLOAT_RE})ns\s*"
        rf"\(logic\s*({FLOAT_RE})ns.*route\s*({FLOAT_RE})ns"
    )
    levels_re = re.compile(r"^\s*Logic Levels:\s*(\d+)")

    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        slack_m = slack_re.match(line)
        if slack_m:
            if current is not None:
                paths.append(current)
            current = TimingPath(
                index=len(paths) + 1,
                slack=float(slack_m.group(1)),
                start_line=lineno,
            )
            continue
        if current is None:
            continue
        if match := source_re.match(line):
            current.source = match.group(1)
        elif match := dest_re.match(line):
            current.destination = match.group(1)
        elif match := group_re.match(line):
            current.path_group = match.group(1)
        elif match := delay_re.match(line):
            current.data_delay = float(match.group(1))
            current.logic_delay = float(match.group(2))
            current.route_delay = float(match.group(3))
        elif match := levels_re.match(line):
            current.logic_levels = int(match.group(1))

    if current is not None:
        paths.append(current)
    return paths


def fmt_float(value: float | None, width: int = 6) -> str:
    if value is None:
        return " " * (width - 1) + "-"
    return f"{value:{width}.3f}"


def route_percent(path: TimingPath) -> float | None:
    if path.data_delay is None or path.route_delay is None or path.data_delay == 0:
        return None
    return 100.0 * path.route_delay / path.data_delay


def group_key(path: TimingPath) -> tuple[str, str, str]:
    return (
        normalize_name(path.source),
        normalize_name(path.destination),
        path.path_group,
    )


def print_individual(paths: list[TimingPath], limit: int, module_depth: int) -> None:
    print(f"\nTop {min(limit, len(paths))} individual paths")
    print("-" * 120)
    for path in paths[:limit]:
        r_pct = route_percent(path)
        print(
            f"#{path.index:03d} slack={path.slack:7.3f}ns "
            f"delay={fmt_float(path.data_delay)}ns "
            f"logic={fmt_float(path.logic_delay)}ns "
            f"route={fmt_float(path.route_delay)}ns "
            f"route%={fmt_float(r_pct, 6)} "
            f"levels={path.logic_levels if path.logic_levels is not None else '-':>2} "
            f"line={path.start_line}"
        )
        print(f"    src: {path.source}")
        print(f"    dst: {path.destination}")
        if module_depth > 0:
            print(
                "    mod: "
                f"{module_head(path.source, module_depth)} -> "
                f"{module_head(path.destination, module_depth)}"
            )


def print_groups(paths: list[TimingPath], limit: int, module_depth: int) -> None:
    groups: dict[tuple[str, str, str], list[TimingPath]] = collections.defaultdict(list)
    for path in paths:
        groups[group_key(path)].append(path)

    ranked = sorted(groups.values(), key=lambda ps: (min(p.slack for p in ps), -len(ps)))
    print(f"\nTop {min(limit, len(ranked))} grouped path families")
    print("-" * 120)
    for idx, members in enumerate(ranked[:limit], 1):
        worst = min(members, key=lambda p: p.slack)
        avg_slack = statistics.fmean(p.slack for p in members)
        avg_delay_values = [p.data_delay for p in members if p.data_delay is not None]
        avg_delay = statistics.fmean(avg_delay_values) if avg_delay_values else None
        avg_route_values = [route_percent(p) for p in members if route_percent(p) is not None]
        avg_route = statistics.fmean(avg_route_values) if avg_route_values else None
        logic_values = [p.logic_levels for p in members if p.logic_levels is not None]
        max_levels = max(logic_values) if logic_values else None

        print(
            f"[{idx:02d}] count={len(members):3d} "
            f"worst={worst.slack:7.3f}ns avg={avg_slack:7.3f}ns "
            f"delay_avg={fmt_float(avg_delay)}ns "
            f"route%_avg={fmt_float(avg_route, 6)} "
            f"levels_max={max_levels if max_levels is not None else '-':>2}"
        )
        print(f"     src_pat: {normalize_name(worst.source)}")
        print(f"     dst_pat: {normalize_name(worst.destination)}")
        if module_depth > 0:
            print(
                "     module:  "
                f"{module_head(worst.source, module_depth)} -> "
                f"{module_head(worst.destination, module_depth)}"
            )


def print_module_pairs(paths: list[TimingPath], limit: int, module_depth: int) -> None:
    pairs: dict[tuple[str, str], list[TimingPath]] = collections.defaultdict(list)
    for path in paths:
        pairs[(module_head(path.source, module_depth),
               module_head(path.destination, module_depth))].append(path)

    ranked = sorted(pairs.items(), key=lambda item: (min(p.slack for p in item[1]), -len(item[1])))
    print(f"\nTop {min(limit, len(ranked))} module pairs")
    print("-" * 120)
    for idx, ((src, dst), members) in enumerate(ranked[:limit], 1):
        worst = min(p.slack for p in members)
        avg = statistics.fmean(p.slack for p in members)
        print(
            f"[{idx:02d}] count={len(members):3d} "
            f"worst={worst:7.3f}ns avg={avg:7.3f}ns "
            f"{src} -> {dst}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Vivado report_timing text file")
    parser.add_argument("--top", type=int, default=20, help="number of entries to print")
    parser.add_argument(
        "--module-depth",
        type=int,
        default=3,
        help="hierarchy depth used for module-pair summaries",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="include non-violating paths if the report contains them",
    )
    args = parser.parse_args()

    all_paths = parse_report(args.report)
    if not all_paths:
        raise SystemExit(f"No timing paths parsed from {args.report}")
    if not args.all:
        paths = [p for p in all_paths if p.slack < 0.0]
    else:
        paths = all_paths
    if not paths:
        met_worst = min(p.slack for p in all_paths)
        met_best = max(p.slack for p in all_paths)
        print(
            f"Report: {args.report}\n"
            "Paths parsed: 0 violating paths "
            f"({len(all_paths)} total listed, worst_listed_slack={met_worst:.3f}ns, "
            f"best_listed_slack={met_best:.3f}ns)\n"
            "Use --all to inspect timing paths that already meet constraints."
        )
        return 0
    paths.sort(key=lambda p: p.slack)

    worst = paths[0].slack
    best = paths[-1].slack
    print(
        f"Report: {args.report}\n"
        f"Paths parsed: {len(paths)}  worst_slack={worst:.3f}ns "
        f"best_listed_slack={best:.3f}ns"
    )
    print_individual(paths, args.top, args.module_depth)
    print_groups(paths, args.top, args.module_depth)
    print_module_pairs(paths, args.top, args.module_depth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
