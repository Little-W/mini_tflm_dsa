#!/usr/bin/env python3
"""Validate bounded Conv geometry next-use prediction against full request traces.

The forward traces are generated from checked-in TFLite shapes and the current
production C tiling planner on each invocation. This script independently
inverts convolution geometry.  It neither measures
new replacement RTL nor uses a pre-expanded next-use table for prediction.

A logical event is (p-block, output-group, q-tile, output-position), not a run
of equal addresses.  In the supported domain it reads exactly one aligned
16-byte channel fragment, in four increasing word requests.  Prediction is
after that complete event, never between its four word requests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
from trace_model import generated_layers, generate_requests
INF = 0xFFFFFFFF


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


@dataclass(frozen=True)
class Geometry:
    input_base: int
    input_h: int
    input_w: int
    input_c: int
    group_c: int
    group_offset: int
    kernel_h: int
    kernel_w: int
    output_h: int
    output_w: int
    stride_h: int
    stride_w: int
    dilation_h: int
    dilation_w: int
    pad_top: int
    pad_left: int
    r: int
    groups: int
    size: int = 16
    line_bytes: int = 16
    input_s16: bool = False

    @property
    def positions(self) -> int:
        return self.output_h * self.output_w

    @property
    def reduction(self) -> int:
        return self.kernel_h * self.kernel_w * self.group_c

    @property
    def q_tiles(self) -> int:
        return (self.reduction + self.size - 1) // self.size

    @property
    def p_blocks(self) -> int:
        return (self.positions + self.r * self.size - 1) // (self.r * self.size)

    @property
    def rank_space(self) -> int:
        return self.p_blocks * self.groups * self.q_tiles * self.r * self.size

    def unsupported_reasons(self) -> list[str]:
        reasons = []
        if self.input_s16:
            reasons.append("input must be s8")
        if self.size != 16 or self.line_bytes != 16:
            reasons.append("SIZE and line size must both be 16")
        if any(value <= 0 for value in (
            self.input_h, self.input_w, self.input_c, self.group_c,
            self.kernel_h, self.kernel_w, self.output_h, self.output_w,
            self.dilation_h, self.dilation_w, self.groups,
        )):
            reasons.append("dimensions, dilation and output groups must be positive")
        if self.input_base < 0 or self.input_base >= 1 << 32:
            reasons.append("input base must fit unsigned 32 bits")
        if self.group_offset < 0 or self.group_offset + self.group_c > self.input_c:
            reasons.append("group channel interval must be within the input pixel")
        if self.pad_top < 0 or self.pad_left < 0:
            reasons.append("leading padding must be nonnegative")
        if any(value % 16 for value in (
            self.input_base, self.input_c, self.group_c, self.group_offset,
        )):
            reasons.append("base, Cin, group C and group offset must be 16-byte aligned")
        if not all(power_of_two(value) for value in (self.r, self.stride_h, self.stride_w)):
            reasons.append("R and both strides must be powers of two")
        if self.kernel_h * self.kernel_w > 25:
            reasons.append("kernel tap count exceeds 25")
        if self.input_base + self.input_h * self.input_w * self.input_c > 1 << 32:
            reasons.append("input byte span exceeds unsigned 32-bit address space")
        # Use the complete rectangular schedule, including tail/padding holes.
        # Reserving ffffffff for INF prevents wrapping or sentinel collisions.
        if self.r > 0 and self.size > 0 and self.groups > 0:
            if not 0 < self.rank_space < INF:
                reasons.append("complete schedule rank space must be below 0xffffffff")
        return reasons

    @classmethod
    def from_layer(cls, layer: dict) -> "Geometry":
        p = layer["parameters"]
        return cls(
            layer["tensors"]["input"]["address"], *p[:9],
            *p[10:16], layer["tiling"]["ia_reuse"],
            layer["tiling"]["col_groups"], size=layer["size"],
        )


@dataclass(frozen=True)
class Current:
    p: int
    q: int
    group: int


@dataclass(frozen=True)
class Prediction:
    next_rank: int
    remaining_count: int


@dataclass(frozen=True)
class LineEvent:
    index: int
    line: int
    first_request: int
    current: Current
    rank: int


def rank_of(g: Geometry, current: Current) -> int:
    pb, in_block = divmod(current.p, g.r * g.size)
    rtile, row = divmod(in_block, g.size)
    qtile = current.q // g.size
    return (((pb * g.groups + current.group) * g.q_tiles + qtile) * g.r + rtile) * g.size + row


def source_of(g: Geometry, current: Current) -> tuple[int, int, int]:
    """Direct Conv address mapping, used only to check supplied event metadata."""
    oy, ox = divmod(current.p, g.output_w)
    tap, ch = divmod(current.q, g.group_c)
    ky, kx = divmod(tap, g.kernel_w)
    return (oy * g.stride_h + ky * g.dilation_h - g.pad_top,
            ox * g.stride_w + kx * g.dilation_w - g.pad_left, ch)


def source_of_line(g: Geometry, line: int) -> tuple[int, int, int]:
    offset = line * g.line_bytes - g.input_base
    if not 0 <= offset < g.input_h * g.input_w * g.input_c:
        raise ValueError("line lies outside the configured input")
    pixel, absolute_ch = divmod(offset, g.input_c)
    iy, ix = divmod(pixel, g.input_w)
    ch = absolute_ch - g.group_offset
    if ch < 0 or ch + g.line_bytes > g.group_c or ch % g.line_bytes:
        raise ValueError("line lies outside the aligned group channel fragments")
    return iy, ix, ch


def predict(g: Geometry, current: Current, iy: int, ix: int, ch: int) -> Prediction:
    """Find future uses by at most Kh*Kw inverse taps, without a future trace.

    Each tap produces zero or one output position for this input fragment.
    Its output-group loop is summarized arithmetically, not enumerated.
    """
    if not (0 <= iy < g.input_h and 0 <= ix < g.input_w and
            0 <= ch <= g.group_c - 16 and ch % 16 == 0):
        return Prediction(INF, 0)
    cur_pb, cur_in_block = divmod(current.p, g.r * g.size)
    cur_within = (current.q // g.size) * g.r * g.size + cur_in_block
    next_rank, remaining = INF, 0
    for ky in range(g.kernel_h):
        numerator_y = iy + g.pad_top - ky * g.dilation_h
        if numerator_y < 0 or numerator_y % g.stride_h:
            continue
        oy = numerator_y // g.stride_h
        if oy >= g.output_h:
            continue
        for kx in range(g.kernel_w):
            numerator_x = ix + g.pad_left - kx * g.dilation_w
            if numerator_x < 0 or numerator_x % g.stride_w:
                continue
            ox = numerator_x // g.stride_w
            if ox >= g.output_w:
                continue
            p = oy * g.output_w + ox
            pb, in_block = divmod(p, g.r * g.size)
            if pb < cur_pb:
                continue
            q = (ky * g.kernel_w + kx) * g.group_c + ch
            within = (q // g.size) * g.r * g.size + in_block
            if pb > cur_pb:
                first_group = 0
            else:
                first_group = current.group + (within <= cur_within)
            if first_group >= g.groups:
                continue
            remaining += g.groups - first_group
            candidate = rank_of(g, Current(p, q, first_group))
            if candidate <= rank_of(g, current):
                raise AssertionError("inverse candidate is not strictly in the future")
            next_rank = min(next_rank, candidate)
    return Prediction(next_rank, remaining)


def logical_events(g: Geometry, requests: list) -> list[LineEvent]:
    """Group by schedule identity; equal line addresses do not erase events."""
    groups = []
    previous_key = None
    for number, req in enumerate(requests):
        if req.index != number:
            raise AssertionError("trace request indexes must be contiguous")
        key = (req.row_group, req.output_group, req.reduction_tile, req.position)
        if key != previous_key:
            groups.append([])
            previous_key = key
        groups[-1].append(req)
    events = []
    for group in groups:
        first = group[0]
        cur = Current(first.position, first.reduction_tile * 16, first.output_group)
        expected_coords = source_of(g, cur)
        if expected_coords != source_of_line(g, first.line):
            raise AssertionError(("forward and address metadata differ", expected_coords, first.line))
        if len(group) != 4:
            raise AssertionError(("logical line event must have exactly four word requests", len(group)))
        for word_index, req in enumerate(group):
            if (req.line != first.line or req.address != first.line * 16 + word_index * 4 or
                req.word != req.address // 4 or req.reduction != cur.q + word_index * 4 or
                req.row_group != cur.p // (g.r * 16) or
                req.position_tile != cur.p // 16):
                raise AssertionError(("event is not one increasing complete 16-byte fragment", vars(req)))
        rank = rank_of(g, cur)
        if events and rank <= events[-1].rank:
            raise AssertionError("logical-event ranks must strictly increase")
        events.append(LineEvent(len(events), first.line, first.index, cur, rank))
    return events


def check_events(g: Geometry, requests: list) -> tuple[dict, list[dict]]:
    events = logical_events(g, requests)
    future_rank, future_count = {}, Counter()
    expected = [None] * len(events)
    for event in reversed(events):
        expected[event.index] = Prediction(future_rank.get(event.line, INF), future_count[event.line])
        future_rank[event.line] = event.rank
        future_count[event.line] += 1
    digest = hashlib.sha256()
    vectors = []
    finite = cross_pb = cross_group = same_line_neighbor = 0
    maximum_remaining = maximum_gap = 0
    for event, reference in zip(events, expected):
        iy, ix, ch = source_of_line(g, event.line)
        calculated = predict(g, event.current, iy, ix, ch)
        if calculated != reference:
            raise AssertionError({"event": asdict(event), "source": [iy, ix, ch],
                                  "prediction": asdict(calculated), "trace": asdict(reference)})
        maximum_remaining = max(maximum_remaining, calculated.remaining_count)
        if calculated.next_rank != INF:
            finite += 1
            maximum_gap = max(maximum_gap, calculated.next_rank - event.rank)
            current_phase = event.rank // (g.q_tiles * g.r * 16)
            next_phase = calculated.next_rank // (g.q_tiles * g.r * 16)
            cross_group += current_phase != next_phase and current_phase // g.groups == next_phase // g.groups
            cross_pb += current_phase // g.groups != next_phase // g.groups
        if event.index and events[event.index - 1].line == event.line:
            same_line_neighbor += 1
        digest.update(f"{event.rank},{event.line},{calculated.next_rank},{calculated.remaining_count}\n".encode())
        vectors.append({"input_y": iy, "input_x": ix, "channel": ch,
                        "current_p": event.current.p, "current_q": event.current.q,
                        "current_group": event.current.group, "current_rank": event.rank,
                        "expected_next_rank": calculated.next_rank,
                        "expected_remaining_count": calculated.remaining_count})
    return {
        "passed": True, "word_requests": len(requests), "logical_line_events": len(events),
        "next_rank_checks": len(events), "remaining_count_checks": len(events),
        "finite_next_use_events": finite, "no_future_use_events": len(events) - finite,
        "next_use_crosses_p_block": cross_pb, "next_use_crosses_output_group_in_same_block": cross_group,
        "max_remaining_count": maximum_remaining, "max_next_rank_distance": maximum_gap,
        "consecutive_equal_line_distinct_events": same_line_neighbor,
        "four_increasing_word_requests_per_event": True,
        "rank_space": g.rank_space, "last_observed_rank": events[-1].rank if events else None,
        "prediction_digest_sha256": digest.hexdigest(),
    }, vectors


def synthetic_requests(g: Geometry) -> list[SimpleNamespace]:
    """Independent scalar forward address sequence, including the word holder."""
    result, last_word = [], None
    for pb, pbase in enumerate(range(0, g.positions, g.r * g.size)):
        for wg in range(g.groups):
            for qt, qbase in enumerate(range(0, g.reduction, g.size)):
                for p0 in range(pbase, min(pbase + g.r * g.size, g.positions), g.size):
                    for p in range(p0, min(p0 + g.size, g.positions)):
                        oy, ox = divmod(p, g.output_w)
                        for q in range(qbase, min(qbase + g.size, g.reduction)):
                            tap, channel = divmod(q, g.group_c)
                            ky, kx = divmod(tap, g.kernel_w)
                            iy = oy * g.stride_h + ky * g.dilation_h - g.pad_top
                            ix = ox * g.stride_w + kx * g.dilation_w - g.pad_left
                            if not (0 <= iy < g.input_h and 0 <= ix < g.input_w):
                                continue
                            address = g.input_base + (iy * g.input_w + ix) * g.input_c + g.group_offset + channel
                            word = address // 4
                            if word == last_word:
                                continue
                            last_word = word
                            result.append(SimpleNamespace(index=len(result), address=address, word=word,
                                line=address // 16, position=p, reduction=q, row_group=pb,
                                output_group=wg, reduction_tile=qt, position_tile=p0 // g.size))
    return result


def synthetic_geometries() -> list[tuple[str, Geometry]]:
    return [
        ("grouped_dilation_and_tail", Geometry(0x10010, 13, 17, 64, 32, 16, 3, 5, 8, 5, 2, 4, 3, 2, 4, 5, 2, 3)),
        # The last live row of one q-tile and first live row of the next q-tile
        # have the same line.  They must remain two events, each with four words.
        ("equal_line_across_distinct_events", Geometry(0x10000, 1, 1, 16, 16, 0, 1, 2, 1, 2, 1, 1, 1, 1, 0, 1, 1, 3)),
        ("tap_limit_25_dilation", Geometry(0x10000, 9, 11, 32, 16, 16, 5, 5, 9, 6, 1, 2, 2, 3, 4, 6, 1, 2)),
        ("r4_partial_block", Geometry(0x10000, 5, 7, 96, 96, 0, 1, 1, 5, 7, 1, 1, 1, 1, 0, 0, 4, 3)),
        ("stride4_sparse_taps", Geometry(0x10000, 23, 19, 16, 16, 0, 3, 3, 6, 5, 4, 4, 3, 5, 2, 5, 2, 2)),
    ]


def check_guards() -> list[dict]:
    base = Geometry(0x10000, 8, 8, 32, 16, 16, 3, 3, 8, 8, 1, 1, 1, 1, 1, 1, 2, 1)
    if base.unsupported_reasons():
        raise AssertionError("guard baseline should be supported")
    bad = [
        ("s16_input", {"input_s16": True}), ("size8", {"size": 8}),
        ("line32", {"line_bytes": 32}), ("unaligned_base", {"input_base": 0x10001}),
        ("unaligned_cin", {"input_c": 33}), ("unaligned_group", {"group_c": 15}),
        ("unaligned_group_offset", {"group_offset": 1}), ("nonpower_r", {"r": 3}),
        ("nonpower_stride", {"stride_w": 3}), ("too_many_taps", {"kernel_h": 6, "kernel_w": 5}),
        ("rank32_overflow", {"groups": 1 << 30}),
        ("input_span_overflow", {"input_base": 0xFFFFFFF0}),
        ("zero_dilation", {"dilation_h": 0}),
    ]
    result = []
    for name, changes in bad:
        reasons = replace(base, **changes).unsupported_reasons()
        if not reasons:
            raise AssertionError((name, "missing fast-path rejection"))
        result.append({"case": name, "rejected": True, "reasons": reasons})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/conv_replacement/geometry/validation.json")
    parser.add_argument("--vectors", type=Path,
                        help="optional JSON vectors for the standalone RTL predictor test")
    args = parser.parse_args()
    bundle = generated_layers(args.out.parent / "geometry")
    report = {
        "verification_level": "OFFLINE geometry inverse checked against freshly enumerated forward request traces; no RTL executed",
        "passed": False, "new_replacement_rtl_executed": False,
        "sources": {
            "oracle": {"path": relative(Path(__file__)), "sha256": sha256(Path(__file__))},
            "forward_model": {"path": "test/conv_replacement/trace_model.py", "sha256": sha256(ROOT / "test/conv_replacement/trace_model.py")},
        },
        "scope": {
            "input": "s8", "size": 16, "line_bytes": 16,
            "required_alignment_bytes": 16,
            "aligned_fields": ["input_base", "input_c", "group_c", "group_offset"],
            "power_of_two_fields": ["R", "stride_h", "stride_w"],
            "dilation": "arbitrary positive integer; exact divisibility checked for both strides",
            "max_kernel_taps": 25, "rank_space_must_be_less_than": INF,
            "out_of_domain": "ordinary cache policy remains required; not approximated by this oracle",
        },
        "event_key": ["p_block", "output_group", "q_tile", "output_position"],
        "rank_formula": "(((p_block*groups+output_group)*Q+q_tile)*R+position_tile_within_block)*16+row",
        "no_future_rank": INF,
        "remaining_count_definition": "number of complete later line events, excluding the entire current four-word event",
        "word_holder_reason": "Each supported event consumes word offsets 0,4,8,12. Even if the next logical event has the same line, its first word 0 differs from the previous last word 12. Padding emits no request and does not change this result.",
        "layers": [], "synthetic_cases": [],
    }
    vector_sets = []
    for layer in bundle["layers"]:
        g = Geometry.from_layer(layer)
        requests = generate_requests(layer)
        entry = {"layer_id": layer["layer_id"], "geometry": asdict(g),
                 "source_word_requests": len(requests)}
        reasons = g.unsupported_reasons()
        entry["supported"] = not reasons
        if reasons:
            entry["skip_reasons"] = reasons
            print("GEOMETRY_SKIP", layer["layer_id"], "; ".join(reasons), flush=True)
        else:
            checked, vectors = check_events(g, requests)
            entry.update(checked)
            vector_sets.append({"case": layer["layer_id"], "source": "checked-in real CNN shape / current C tiling / freshly enumerated forward sequence",
                                "geometry": asdict(g), "vectors": vectors})
            print("GEOMETRY_MATCH", layer["layer_id"], checked["logical_line_events"], "events", flush=True)
        report["layers"].append(entry)
    for name, g in synthetic_geometries():
        if g.unsupported_reasons():
            raise AssertionError((name, g.unsupported_reasons()))
        checked, vectors = check_events(g, synthetic_requests(g))
        report["synthetic_cases"].append({"case": name, "geometry": asdict(g), **checked})
        vector_sets.append({"case": name, "source": "synthetic forward scalar address enumeration",
                            "geometry": asdict(g), "vectors": vectors})
        print("GEOMETRY_SYNTHETIC_MATCH", name, checked["logical_line_events"], "events", flush=True)
    report["guard_cases"] = check_guards()
    qualified = [layer for layer in report["layers"] if layer["supported"]]
    report["totals"] = {
        "real_layers": len(report["layers"]), "supported_real_layers": len(qualified),
        "unsupported_real_layers": len(report["layers"]) - len(qualified),
        "real_logical_line_events": sum(layer["logical_line_events"] for layer in qualified),
        "real_word_requests": sum(layer["word_requests"] for layer in qualified),
        "synthetic_cases": len(report["synthetic_cases"]),
        "synthetic_logical_line_events": sum(case["logical_line_events"] for case in report["synthetic_cases"]),
        "rejected_guard_cases": len(report["guard_cases"]),
    }
    if args.vectors:
        args.vectors.parent.mkdir(parents=True, exist_ok=True)
        args.vectors.write_text(json.dumps({"inf": INF, "cases": vector_sets}, separators=(",", ":")) + "\n")
        report["vectors"] = {"path": relative(args.vectors), "sha256": sha256(args.vectors)}
    report["passed"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print("GEOMETRY_VALIDATION_PASS", json.dumps(report["totals"], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
