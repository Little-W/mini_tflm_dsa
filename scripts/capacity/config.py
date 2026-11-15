"""Read literal Make configuration without executing Make or shell expressions."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile

from . import model

DEFAULTS = {
    "PCR_ENGINE": 0, "SIZE": 4, "IA_CACHE_BLOCKS": 4, "PS_FRAME_COUNT": 8,
    "AXI_READ_OUTSTANDING": 4, "PANEL_MAX_R": 16, "PANEL_MAX_W": 16,
    "PS_POOL_BYTES": 179200, "PS_FORCE_RAW": 0,
    "CAPACITY_BUDGET_BYTES": 262144,
    "CAPACITY_BUDGET_SCOPE": "logical-state", "CAPACITY_REPRESENTATION": "nominal3",
}
MANAGED_KEYS = ("PCR_ENGINE", "SIZE", "PANEL_MAX_R", "PANEL_MAX_W", "PS_POOL_BYTES",
                "PS_FORCE_RAW", "CAPACITY_BUDGET_BYTES", "CAPACITY_BUDGET_SCOPE",
                "CAPACITY_REPRESENTATION")
INTEGER_KEYS = {key for key, value in DEFAULTS.items() if type(value) is int}
ASSIGNMENT = re.compile(r"^\s*(?:(?:export|override)\s+)?([A-Z][A-Z0-9_]*)\s*(\?=|:=|=)\s*(.*?)\s*$")
INTEGER = re.compile(r"[+-]?(?:[0-9]+|0[xX][0-9a-fA-F]+)\Z")


def literal_value(key, text):
    if key not in DEFAULTS:
        raise ValueError(f"unsupported configuration key: {key}")
    text = text.strip()
    if key in INTEGER_KEYS:
        if not INTEGER.fullmatch(text):
            raise ValueError(f"{key} must be an integer literal, not a Make expression")
        return int(text, 16 if "x" in text.lower() else 10)
    allowed = model.SCOPES if key == "CAPACITY_BUDGET_SCOPE" else model.REPRESENTATIONS
    if text not in allowed:
        raise ValueError(f"{key} must be one of {allowed}")
    return text


def read_config(path):
    """Return supported literal assignments; unrelated lines are left untouched.

    Missing keys are not invented here. Callers may merge DEFAULTS before
    checking a partial override file. Duplicate supported assignments are an
    error because Make's assignment operators otherwise have subtle precedence.
    """
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        source = line.split("#", 1)[0].strip()
        if not source:
            continue
        match = ASSIGNMENT.fullmatch(source)
        if match and match[1] in DEFAULTS:
            key = match[1]
            if key in values:
                raise ValueError(f"{path}:{number}: duplicate assignment for {key}")
            try:
                values[key] = literal_value(key, match[3])
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
        elif re.match(r"(?:export\s+|override\s+)?(" + "|".join(DEFAULTS) + r")\s*(?:[?:+!]?=|\s)", source):
            raise ValueError(f"{path}:{number}: unsupported assignment syntax")
    return values


def parse_override(text):
    if "=" not in text:
        raise ValueError("--set requires KEY=VALUE")
    key, value = text.split("=", 1)
    key = key.strip()
    return key, literal_value(key, value)


def validate_config(values, require_pcr=False):
    missing = [key for key in MANAGED_KEYS if key not in values]
    if missing:
        raise ValueError("configuration is missing: " + ", ".join(missing))
    normalized = {**DEFAULTS, **values}
    for key in INTEGER_KEYS:
        if type(normalized[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for key in ("PCR_ENGINE", "PS_FORCE_RAW"):
        if normalized[key] not in (0, 1):
            raise ValueError(f"{key} must be 0 or 1")
    size = normalized["SIZE"]
    if not (1 <= size <= 32) or size & (size - 1):
        raise ValueError("SIZE must be a power of two in 1..32")
    for key in ("IA_CACHE_BLOCKS", "PS_FRAME_COUNT", "AXI_READ_OUTSTANDING", "CAPACITY_BUDGET_BYTES"):
        if normalized[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if normalized["CAPACITY_BUDGET_SCOPE"] not in model.SCOPES:
        raise ValueError("unsupported CAPACITY_BUDGET_SCOPE")
    if normalized["CAPACITY_REPRESENTATION"] not in model.REPRESENTATIONS:
        raise ValueError("unsupported CAPACITY_REPRESENTATION")
    pool = normalized["PS_POOL_BYTES"]
    if pool <= 0 or pool % model.PAGE_BYTES:
        raise ValueError("PS_POOL_BYTES must be a positive multiple of 256")
    model.state_bits(normalized["PANEL_MAX_R"], normalized["PANEL_MAX_W"], pool // model.PAGE_BYTES)
    if require_pcr and normalized["PCR_ENGINE"] != 1:
        raise ValueError("this operation requires PCR_ENGINE=1")
    if normalized["PCR_ENGINE"]:
        if size != model.TILE:
            raise ValueError("the GEMPACT K64 capacity model requires SIZE=16")
        expected_raw = int(normalized["CAPACITY_REPRESENTATION"] == "raw32")
        if normalized["PS_FORCE_RAW"] != expected_raw:
            raise ValueError("PS_FORCE_RAW disagrees with CAPACITY_REPRESENTATION")
        alloc = allocation_from_config(normalized)
        if alloc["unused_budget_bytes"] < 0:
            raise ValueError(f"configured {normalized['CAPACITY_BUDGET_SCOPE']} uses "
                             f"{alloc['budget_used_bytes']:g} B, exceeding "
                             f"CAPACITY_BUDGET_BYTES={normalized['CAPACITY_BUDGET_BYTES']}")
    return normalized


def allocation_from_config(values):
    return model.allocation(values["PANEL_MAX_R"], values["PANEL_MAX_W"],
                            values["PS_POOL_BYTES"] // model.PAGE_BYTES,
                            values["CAPACITY_BUDGET_BYTES"], values["CAPACITY_BUDGET_SCOPE"])


def atomic_write(path, text):
    """Replace one file atomically; identical content does not change its mtime."""
    path = Path(path).resolve()
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_config(path, updates):
    """Update capacity fields only, preserving other settings and comments."""
    path = Path(path).resolve()
    unexpected = set(updates) - set(MANAGED_KEYS)
    if unexpected:
        raise ValueError("cannot update unrelated configuration keys: " + ", ".join(sorted(unexpected)))
    existing = read_config(path) if path.exists() else {}
    combined = validate_config({**DEFAULTS, **existing, **updates})
    for key, value in updates.items():
        literal_value(key, str(value))
        if combined[key] != value:
            raise ValueError(f"invalid update for {key}")
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    lines, replaced = [], set()
    for line in original.splitlines():
        source, separator, comment = line.partition("#")
        match = ASSIGNMENT.fullmatch(source.strip())
        if match and match[1] in updates:
            key = match[1]
            line = f"{key} ?= {updates[key]}"
            if separator:
                line += "  #" + comment
            replaced.add(key)
        lines.append(line)
    new_keys = [key for key in MANAGED_KEYS if key in updates and key not in replaced]
    if new_keys:
        if lines and lines[-1]:
            lines.append("")
        lines.append("# GEMPACT capacity parameters (updated by scripts/capacity/solve.py)")
        lines.extend(f"{key} ?= {updates[key]}" for key in new_keys)
    return atomic_write(path, "\n".join(lines) + "\n")


def emit_c_header(values):
    values = validate_config(values)
    lines = ["/* Generated from the selected npu.mk; do not edit this header. */",
             "#ifndef TFLM_AI_DSA_NPU_CONFIG_H", "#define TFLM_AI_DSA_NPU_CONFIG_H", ""]
    for key in DEFAULTS:
        value = values[key]
        literal = f'"{value}"' if isinstance(value, str) else str(value)
        lines.append(f"#define NPU_CONFIG_{key} {literal}")
    alloc = allocation_from_config(values)
    lines += ["", "/* PCR quantities apply only when NPU_CONFIG_PCR_ENGINE is 1. */"]
    for name, value in (("A_PANEL_BYTES", alloc["a_panel_bytes"]),
                        ("B_PANEL_BYTES", alloc["b_panel_bytes"]),
                        ("PS_POOL_PAGES", alloc["ps_pool_pages"]),
                        ("BUFFER_RAM_BYTES", alloc["buffer_ram_bytes"]),
                        ("LOGICAL_STATE_BITS", alloc["logical_state_bits"])):
        lines.append(f"#define NPU_CONFIG_{name} {value}")
    return "\n".join(lines + ["", "#endif", ""])
