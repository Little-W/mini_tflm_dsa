"""Read literal Make configuration without executing Make or shell expressions."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile

from . import model, im2col_cache

DEFAULTS = {
    "PCR_ENGINE": 1, "SIZE": 16, "IA_CACHE_BLOCKS": 4, "PS_FRAME_COUNT": 16,
    "NPU_AXI_DATA_WIDTH": 64,
    "IM2COL_CACHE_BYTES": im2col_cache.DEFAULT_BYTES,
    "SHARED_BANK_BYTES": 2048, "SHARED_BANK_COUNT": 7,
    "AXI_READ_OUTSTANDING": 4, "PS_POOL_BYTES": 12288, "PS_FORCE_RAW": 0,
    "CAPACITY_BUDGET_BYTES": 131072,
    "CAPACITY_BUDGET_SCOPE": "buffer-ram", "CAPACITY_REPRESENTATION": "adaptive",
}
MANAGED_KEYS = tuple(DEFAULTS)
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


def validate_config(values, require_pcr=False, *, check_budget=True, state_report=None):
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
    if normalized["NPU_AXI_DATA_WIDTH"] not in (32, 64):
        raise ValueError("NPU_AXI_DATA_WIDTH must be 32 or 64")
    im2col_cache.validate_bytes(normalized["IM2COL_CACHE_BYTES"])
    if normalized["SHARED_BANK_BYTES"] not in (2048, 4096, 8192):
        raise ValueError("SHARED_BANK_BYTES must be 2048, 4096 or 8192")
    if normalized["SHARED_BANK_COUNT"] not in range(6, 10):
        raise ValueError("SHARED_BANK_COUNT must be in 6..9")
    if normalized["AXI_READ_OUTSTANDING"] not in range(1, 17):
        raise ValueError("AXI_READ_OUTSTANDING must be in 1..16")
    if normalized["CAPACITY_BUDGET_BYTES"] <= 0:
        raise ValueError("CAPACITY_BUDGET_BYTES must be positive")
    if normalized["CAPACITY_BUDGET_SCOPE"] not in model.SCOPES:
        raise ValueError("unsupported CAPACITY_BUDGET_SCOPE")
    if normalized["CAPACITY_REPRESENTATION"] not in model.REPRESENTATIONS:
        raise ValueError("unsupported CAPACITY_REPRESENTATION")
    normalized["CAPACITY_REPRESENTATION"] = "raw32" if normalized["PS_FORCE_RAW"] else "adaptive"
    model.geometry(normalized["IA_CACHE_BLOCKS"], normalized["PS_FRAME_COUNT"],
                   normalized["PS_POOL_BYTES"], normalized["SIZE"], bool(normalized["PCR_ENGINE"]),
                   **shared_geometry(normalized))
    if require_pcr and normalized["PCR_ENGINE"] != 1:
        raise ValueError("this operation requires PCR_ENGINE=1")
    if check_budget:
        alloc = allocation_from_config(normalized, state_report=state_report)
        if alloc["unused_budget_bytes"] < 0:
            raise ValueError(f"configured {normalized['CAPACITY_BUDGET_SCOPE']} uses "
                             f"{alloc['budget_used_bytes']:g} B, exceeding "
                             f"CAPACITY_BUDGET_BYTES={normalized['CAPACITY_BUDGET_BYTES']}")
    return normalized


def axi_data_width(explicit=None, config_path=None):
    """Resolve the NPU AXI4 data width from an override or the selected config."""
    if explicit is None:
        override = os.environ.get("NPU_AXI_DATA_WIDTH")
        if override is not None:
            explicit = literal_value("NPU_AXI_DATA_WIDTH", override)
        else:
            path = Path(config_path or os.environ.get("NPU_CONFIG") or
                        Path(__file__).resolve().parents[2] / "config/npu.mk")
            explicit = read_config(path).get("NPU_AXI_DATA_WIDTH", DEFAULTS["NPU_AXI_DATA_WIDTH"])
    if type(explicit) is not int or explicit not in (32, 64):
        raise ValueError("NPU_AXI_DATA_WIDTH must be 32 or 64")
    return explicit


def selected_config(config_path=None):
    """Read hardware settings without evaluating shell or Make expressions."""
    path = Path(config_path or os.environ.get("NPU_CONFIG") or
                Path(__file__).resolve().parents[2] / "config/npu.mk")
    values = {**DEFAULTS, **read_config(path), **environment_settings()}
    return validate_config(values, check_budget=False)


def environment_settings():
    """Literal hardware overrides applied before explicit command arguments."""
    return {key: literal_value(key, os.environ[key])
            for key in ("NPU_AXI_DATA_WIDTH", "IM2COL_CACHE_BYTES", "SHARED_BANK_BYTES", "SHARED_BANK_COUNT")
            if key in os.environ}


def shared_geometry(values):
    """Physical bank geometry used by the unified compressed or RAW32 store."""
    return dict(bank_bytes=values["SHARED_BANK_BYTES"],
                bank_count=values["SHARED_BANK_COUNT"] if values["PCR_ENGINE"] else None)


def allocation_from_config(values, *, state_report=None):
    from . import elaboration
    report = state_report or elaboration.find_cached(values)
    if report is not None and not elaboration.current_report(values, report):
        raise ValueError("state report does not match the current configuration and sources")
    bits = report["elaborated_state"]["total_bits"] if report is not None else None
    result = model.allocation(values["IA_CACHE_BLOCKS"], values["PS_FRAME_COUNT"],
                              values["PS_POOL_BYTES"], values["CAPACITY_BUDGET_BYTES"],
                              values["CAPACITY_BUDGET_SCOPE"], size=values["SIZE"],
                              compressed=bool(values["PCR_ENGINE"]), measured_state_bits=bits,
                              im2col_cache_bytes=values["IM2COL_CACHE_BYTES"],
                              **shared_geometry(values))
    result["state_measurement"] = None if report is None else {
        "source_identity": report["cache_identity"], "verilator": report["verilator"]}
    return result


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
    return _update_settings(path, updates, MANAGED_KEYS,
                            "Shared NPU capacity parameters")


def update_settings(path, updates):
    """Update any supported hardware setting, preserving unrelated content.

    The interactive editor and solver use the same literal configuration keys.
    """
    return _update_settings(path, updates, tuple(DEFAULTS),
                            "NPU parameters (updated by menuconfig)")


def _update_settings(path, updates, allowed_keys, section_comment):
    path = Path(path).resolve()
    unexpected = set(updates) - set(allowed_keys)
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
    new_keys = [key for key in allowed_keys if key in updates and key not in replaced]
    if new_keys:
        if lines and lines[-1]:
            lines.append("")
        lines.append("# " + section_comment)
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
    lines += ["", "/* Logical buffer sizes; physical memory macro rounding is separate. */"]
    for name, value in (("BUFFER_RAM_BITS", alloc["buffer_ram_bits"]),
                        ("BUFFER_RAM_BYTES", alloc["buffer_ram_bytes"]),
                        ("PS_BUFFER_BITS", alloc["ps_buffer_bits"]),
                        ("MAX_FRAME_ROWS", alloc["max_frame_rows"]),
                        ("LOGICAL_STATE_MEASURED", int(alloc["logical_state_bits"] is not None))):
        lines.append(f"#define NPU_CONFIG_{name} {value}")
    if alloc["logical_state_bits"] is not None:
        lines.append(f"#define NPU_CONFIG_LOGICAL_STATE_BITS {alloc['logical_state_bits']}")
    return "\n".join(lines + ["", "#endif", ""])
