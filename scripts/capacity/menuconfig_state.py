"""Editable NPU configuration state, independent of the terminal interface.

Edits and optimization stay in memory until save(). This module uses the same
capacity model and validation as the batch solver, while allowing temporarily
over-budget drafts so the user can change a budget before optimizing it.
"""
from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import re

from . import config, model, elaboration, im2col_cache


ROOT = Path(__file__).resolve().parents[2]
BYTE_KEYS = {"CAPACITY_BUDGET_BYTES", "PS_POOL_BYTES", "SHARED_BANK_BYTES", "IM2COL_CACHE_BYTES"}
BYTE_AMOUNT = re.compile(r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))\s*(B|KiB|MiB|K|M)\Z",
                         re.IGNORECASE)


def parse_bytes(text):
    """Parse exact whole bytes, optionally using binary K/M or KiB/MiB units."""
    if type(text) is int:
        return text
    if not isinstance(text, str):
        raise ValueError("capacity must be an integer or a byte quantity such as 128 KiB")
    text = text.strip()
    if config.INTEGER.fullmatch(text):
        return int(text, 16 if "x" in text.lower() else 10)
    match = BYTE_AMOUNT.fullmatch(text)
    if match is None:
        raise ValueError("enter integer bytes or a quantity such as 128 KiB or 1.5 MiB")
    unit = match[2].lower()
    scale = 1 if unit == "b" else 1024 if unit in ("k", "kib") else 1024 * 1024
    amount = Fraction(match[1]) * scale
    if amount.denominator != 1:
        raise ValueError("capacity must represent a whole number of bytes")
    return int(amount)


def _field_value(key, value):
    if key not in config.DEFAULTS:
        raise ValueError(f"unsupported configuration key: {key}")
    if key in BYTE_KEYS:
        value = parse_bytes(value)
    elif key in config.INTEGER_KEYS:
        if isinstance(value, str):
            value = config.literal_value(key, value)
        elif type(value) is not int:
            raise ValueError(f"{key} must be an integer")
    else:
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a supported text choice")
        value = config.literal_value(key, value)

    if key in ("PCR_ENGINE", "PS_FORCE_RAW") and value not in (0, 1):
        raise ValueError(f"{key} must be 0 or 1")
    if key == "PS_FORCE_RAW" and value != 1:
        raise ValueError("PS_FORCE_RAW must be 1 for the INT32 partial-sum store")
    if key == "CAPACITY_REPRESENTATION" and value != "raw32":
        raise ValueError("CAPACITY_REPRESENTATION must be raw32")
    if key == "SIZE" and value not in (2, 4, 8, 16, 32):
        raise ValueError("SIZE must be a power of two in 2..32")
    if key == "NPU_AXI_DATA_WIDTH" and value not in (32, 64):
        raise ValueError("NPU_AXI_DATA_WIDTH must be 32 or 64")
    if key == "IM2COL_CACHE_BYTES":
        im2col_cache.validate_bytes(value)
    if key == "SHARED_BANK_BYTES" and value not in (2048, 4096, 8192):
        raise ValueError("SHARED_BANK_BYTES must be 2048, 4096 or 8192")
    if key == "SHARED_BANK_COUNT" and value not in range(6, 10):
        raise ValueError("SHARED_BANK_COUNT must be in 6..9")
    if key == "IA_CACHE_BLOCKS" and (value < 2 or value > 64 or value & (value-1)):
        raise ValueError("IA_CACHE_BLOCKS must be a power of two in 2..64")
    if key == "PS_FRAME_COUNT" and not 1 <= value <= 64:
        raise ValueError("PS_FRAME_COUNT must be in 1..64")
    if key in ("IA_CACHE_BLOCKS", "PS_FRAME_COUNT", "AXI_READ_OUTSTANDING", "CAPACITY_BUDGET_BYTES") and value <= 0:
        raise ValueError(f"{key} must be positive")
    if key == "PS_POOL_BYTES" and (value < 64 or value > model.MAX_POOL_BYTES or value % 64):
        raise ValueError("PS_POOL_BYTES must be a positive multiple of 64")
    return value


class MenuConfigState:
    """A draft configuration with explicit save and external-edit detection.

    capacity_summary() returns ``active``, ``allocation`` (the model's allocation
    dictionary, or None) and ``validation_error`` (a message, or None). Invalid
    cross-field drafts can be inspected and edited; validate/save reject them.
    """

    def __init__(self, config_path, *, overrides=(), workloads_path=None,
                 shapes=None, output_path=None, budget_bytes=None,
                 budget_scope=None, representation=None, verilator="verilator"):
        self.path = Path(config_path).expanduser().resolve()
        self.workloads_path = Path(workloads_path or ROOT / "config/capacity_workloads.json").expanduser().resolve()
        self.output_path = Path(output_path).expanduser().resolve() if output_path is not None else None
        if self.output_path in (self.path, self.workloads_path):
            raise ValueError("solution output must differ from the configuration and workload input")
        if shapes is not None and workloads_path is not None:
            raise ValueError("choose explicit shapes or a workload file, not both")
        self.shapes = model.validate_workloads(shapes) if shapes is not None else None
        self.workload_label = (f"{len(self.shapes)} explicit GEMM shape(s)" if self.shapes is not None
                               else str(self.workloads_path))
        self.last_solution = None
        self._solution_values = None
        self.verilator = verilator
        self.reload()
        for key, value in config.environment_settings().items():
            self.set_value(key, value)
        entries = overrides.items() if isinstance(overrides, dict) else self._override_items(overrides)
        for key, value in entries:
            self.set_value(key, value)
        if budget_bytes is not None:
            self.set_value("CAPACITY_BUDGET_BYTES", budget_bytes)
        if budget_scope is not None:
            self.set_value("CAPACITY_BUDGET_SCOPE", budget_scope)
        if representation is not None:
            self.set_value("CAPACITY_REPRESENTATION", representation)

    @staticmethod
    def _override_items(overrides):
        for item in overrides:
            if not isinstance(item, str) or "=" not in item:
                raise ValueError("configuration overrides require KEY=VALUE")
            key, value = item.split("=", 1)
            yield key.strip(), value

    @property
    def dirty(self):
        return bool(self._missing_keys or self.values != self._baseline_values)

    def reload(self):
        """Discard the draft and reload disk values, without replaying overrides."""
        current = config.read_config(self.path) if self.path.exists() else {}
        baseline_content = self.path.read_bytes() if self.path.exists() else None
        self.values = {**config.DEFAULTS, **current}
        self._baseline_values = dict(self.values)
        self._baseline_content = baseline_content
        self._missing_keys = set(config.DEFAULTS) - set(current)
        self.last_solution = None
        self._solution_values = None

    def set_value(self, key, value):
        """Edit one field, maintaining PCR size and PS policy dependencies."""
        value = _field_value(key, value)
        updated = dict(self.values)
        updated[key] = value
        if key == "PCR_ENGINE" and value:
            updated["SIZE"] = model.TILE
        elif key == "PS_FORCE_RAW":
            updated["CAPACITY_REPRESENTATION"] = "raw32" if value else "adaptive"
        elif key == "CAPACITY_REPRESENTATION":
            updated["PS_FORCE_RAW"] = int(value == "raw32")
        if updated != self.values:
            self.values = updated
            self.last_solution = None
            self._solution_values = None

    def validate(self):
        return config.validate_config(self.values)

    def capacity_summary(self):
        active = True
        validation_error = None
        try:
            self.validate()
        except ValueError as error:
            validation_error = str(error)
        allocation = None
        if active:
            try:
                allocation = config.allocation_from_config(self.values)
            except ValueError as error:
                validation_error = validation_error or str(error)
        return {"active": active, "allocation": allocation,
                "validation_error": validation_error}

    def _workloads(self):
        if self.shapes is not None:
            return model.validate_workloads(self.shapes)
        data = json.loads(self.workloads_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("workloads", data.get("main_shapes"))
        return model.validate_workloads(data)

    def solve(self):
        """Optimize the draft; failure does not modify any value or file."""
        def measure(cache, frames, pool, representation, *, bank_bytes=2048, bank_count=None):
            values = {**self.values, "PCR_ENGINE": 1, "SIZE": 16, "IA_CACHE_BLOCKS": cache,
                      "PS_FRAME_COUNT": frames, "PS_POOL_BYTES": pool,
                      "PS_FORCE_RAW": int(representation=="raw32")}
            if bank_count is not None:
                values.update(SHARED_BANK_BYTES=bank_bytes, SHARED_BANK_COUNT=bank_count)
            report = elaboration.measure(values, verilator=self.verilator)
            if not report["passed"]:
                raise ValueError("elaborated buffers differ from the current capacity model")
            return report["elaborated_state"]["total_bits"]
        result = model.solve(self._workloads(), self.values["CAPACITY_BUDGET_BYTES"],
                             self.values["CAPACITY_BUDGET_SCOPE"],
                             self.values["CAPACITY_REPRESENTATION"],
                             measure=measure if self.values["CAPACITY_BUDGET_SCOPE"]=="logical-state" else None,
                             im2col_cache_bytes=self.values["IM2COL_CACHE_BYTES"],
                             bank_bytes=self.values["SHARED_BANK_BYTES"],
                             cache_blocks=self.values["IA_CACHE_BLOCKS"], frame_count=self.values["PS_FRAME_COUNT"],
                             ps_build_bytes=self.values["PS_POOL_BYTES"])
        allocation = result["allocation"]
        updated = {**self.values, "PCR_ENGINE": 1, "SIZE": model.TILE,
                   "SHARED_BANK_BYTES": allocation["shared_bank_bytes"],
                   "SHARED_BANK_COUNT": allocation["shared_physical_bank_count"],
                   "PS_FORCE_RAW": int(result["representation"] == "raw32")}
        self.values = config.validate_config(updated, require_pcr=True)
        result["configuration_updates"] = {key: self.values[key] for key in config.MANAGED_KEYS}
        result["configuration_path"] = str(self.path)
        self.last_solution = result
        self._solution_values = dict(self.values)
        return result

    def save(self):
        """Validate and atomically save changed settings; return content change.

        A matching optimization report is optional and written before committing
        the configuration, so an unwritable report destination cannot cause the
        editor to report failure after the configuration has already changed.
        The report contains a proposed allocation, not an assertion of saving.
        """
        normalized = self.validate()
        current_content = self.path.read_bytes() if self.path.exists() else None
        if current_content != self._baseline_content:
            raise ValueError("configuration changed outside menuconfig; reload before saving")
        if self.output_path is not None and self.last_solution is not None and self.values == self._solution_values:
            config.atomic_write(self.output_path, json.dumps(self.last_solution, indent=2) + "\n")
        updates = {key: value for key, value in normalized.items()
                   if key in self._missing_keys or value != self._baseline_values.get(key)}
        changed = config.update_settings(self.path, updates) if updates else False
        self.values = normalized
        self._baseline_values = dict(normalized)
        self._baseline_content = self.path.read_bytes() if self.path.exists() else None
        self._missing_keys = set()
        return changed
