#!/usr/bin/env python3
"""Verify all addressable INT32 frame events emitted by the SoC observer."""
import gzip
import hashlib
from pathlib import Path
import re


def event_lines(path: Path, content_hash):
    if not path.exists():
        path = path.with_name(path.name + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for raw in stream:
            content_hash.update(raw)
            yield raw.decode("utf-8").rstrip("\r\n")


def event_digest(path: Path):
    if not path.exists():
        path = path.with_name(path.name + ".gz")
    opener = gzip.open if path.suffix == ".gz" else open
    result = hashlib.sha256()
    with opener(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def verify(path: Path, log: str) -> dict:
    pending = {}
    active = None
    writes = reads = discarded = frames = 0
    write_hash = hashlib.sha256()
    read_hash = hashlib.sha256()
    content_hash = hashlib.sha256()
    header = None
    for ordinal, line in enumerate(event_lines(path, content_hash)):
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        kind = line.split()[0]
        if ordinal == 0:
            header = {key: int(value) for key, value in fields.items()}
            if kind != "H" or any(header.get(key) != value for key, value in
                                  (("version", 3), ("lanes", 16), ("bits", 32))):
                raise ValueError("Unsupported PS event format")
            if header.get("frames", 0) <= 0 or header.get("rows", 0) <= 0:
                raise ValueError("Invalid PS observer capacity")
            continue
        if kind == "F":
            desc = {key: int(value) for key, value in fields.items()}
            if active is not None or not 0 <= desc["frame"] < header["frames"] or not 0 < desc["rows"] <= header["rows"]:
                raise ValueError("Invalid PS frame acceptance")
            required = set() if desc["init"] else {
                (desc["job"], desc["frame"], row) for row in range(desc["rows"])}
            present = {key for key in pending if key[1] == desc["frame"]}
            if present != required:
                raise ValueError("Stored frame differs from accepted descriptor")
            active = dict(desc, write_row=0, read_row=0)
        elif kind in ("W", "R"):
            data = bytes.fromhex(fields["data"])
            key = tuple(int(fields[name]) for name in ("job", "frame", "row"))
            if len(data) != 64 or active is None or key[:2] != (active["job"], active["frame"]):
                raise ValueError("PS row is outside its active frame")
            if kind == "W":
                if active["final"] or key[2] != active["write_row"] or key[2] >= active["rows"] or key in pending:
                    raise ValueError("Invalid PS row replacement")
                pending[key] = data
                active["write_row"] += 1
                writes += 1
                write_hash.update(data)
            else:
                if active["init"] or key[2] != active["read_row"] or pending.pop(key, None) != data:
                    raise ValueError(f"PS replay mismatch at event {ordinal}")
                active["read_row"] += 1
                reads += 1
                read_hash.update(data)
        elif kind == "E":
            if active is None or (int(fields["job"]), int(fields["frame"])) != (active["job"], active["frame"]):
                raise ValueError("PS completion has no matching descriptor")
            if active["write_row"] != (0 if active["final"] else active["rows"]) or active["read_row"] != (0 if active["init"] else active["rows"]):
                raise ValueError("PS frame completed with missing rows")
            active = None
            frames += 1
        elif kind == "X":
            count = int(fields["rows"])
            if count != len(pending):
                raise ValueError("PS reset count differs from pending rows")
            discarded += count
            pending.clear()
            active = None
        else:
            raise ValueError(f"Unknown PS event: {kind}")
    summaries = [line for line in log.splitlines() if line.startswith("PS_STREAM_SUMMARY ")]
    if header is None or len(summaries) != 1:
        raise ValueError("Expected one PS event header and complete summary")
    summary = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", summaries[0])}
    if pending or active is not None or writes != reads + discarded or any(
            summary[key] != value for key, value in
            (("writes", writes), ("reads", reads), ("discarded", discarded), ("frames", frames))):
        raise ValueError("PS frame recovery is incomplete")
    return {"passed": True, "summary": summary,
            "write_data_sha256": write_hash.hexdigest(), "read_data_sha256": read_hash.hexdigest(),
            "event_file_sha256": content_hash.hexdigest()}
