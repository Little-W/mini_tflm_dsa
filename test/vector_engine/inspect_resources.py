#!/usr/bin/env python3
"""Inspect elaborated multipliers and declared storage using Verilator JSON."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def extent(value):
    match = re.fullmatch(r"\[?(-?\d+):(-?\d+)\]?", value)
    if not match:
        raise ValueError("Unresolved elaborated range: " + value)
    return abs(int(match[1]) - int(match[2])) + 1


def dtype_shape(identifier, types):
    dtype = types[identifier]
    kind = dtype["type"]
    if kind in {"REFDTYPE", "ENUMDTYPE", "MEMBERDTYPE"}:
        return dtype_shape(dtype["refDTypep"], types)
    if kind in {"UNPACKARRAYDTYPE", "PACKARRAYDTYPE"}:
        child = dtype_shape(dtype["refDTypep"], types)
        count = extent(dtype["declRange"])
        if kind == "UNPACKARRAYDTYPE":
            return {"dimensions": [count, *child["dimensions"]],
                    "element_bits": child["element_bits"]}
        if child["dimensions"]:
            raise ValueError("Packed array contains an unpacked type")
        return {"dimensions": [], "element_bits": count * child["element_bits"]}
    if kind in {"STRUCTDTYPE", "UNIONDTYPE"}:
        if not dtype.get("packed"):
            raise ValueError("Storage analysis requires a packed aggregate: " + identifier)
        members = [(member, dtype_shape(member["refDTypep"], types))
                   for member in dtype["membersp"]]
        if not members or any(shape["dimensions"] for _, shape in members):
            raise ValueError("Invalid packed aggregate: " + identifier)
        bits = 0
        for member, shape in reversed(members):
            expected_lsb = bits if kind == "STRUCTDTYPE" else 0
            if "lsb" in member and int(member["lsb"]) != expected_lsb:
                raise ValueError("Packed member offset differs from its declared width")
            bits = bits + shape["element_bits"] if kind == "STRUCTDTYPE" else max(bits, shape["element_bits"])
        return {"dimensions": [], "element_bits": bits}
    if kind == "BASICDTYPE":
        if "range" in dtype:
            bits = extent(dtype["range"])
        elif dtype["keyword"] in {"bit", "logic"}:
            bits = 1
        else:
            raise ValueError("Elaborated scalar width is unavailable: " + identifier)
        return {"dimensions": [], "element_bits": bits}
    raise ValueError("Unsupported elaborated data type: " + kind)


def inspect(repository, out, executable, top, tile, pes, bus_width, window_lanes, shared_quant):
    out.mkdir(parents=True, exist_ok=True)
    conv = repository / "rtl/npu/conv"
    if top == "vector_engine":
        names = ["conv_im2col_pkg.sv", "vector_engine_pkg.sv",
                 "vector_pe.sv", "vector_softmax.sv", "vector_config_check.sv", "vector_writeback.sv", "vector_round_shift.sv", "vector_scalar_multiplier.sv", "vector_quant_params.sv", "vector_engine.sv"]
        parameters = [f"-GTILE={tile}", f"-GPE_COUNT={pes}", f"-GBUS_WIDTH={bus_width}"]
        engine_text = (conv / "vector_engine.sv").read_text()
        if "parameter bit SHARED_QUANT_ENABLE" in engine_text:
            parameters.append(f"-GSHARED_QUANT_ENABLE={int(shared_quant)}")
        if "parameter int WINDOW_LANES" in engine_text:
            parameters.append(f"-GWINDOW_LANES={window_lanes}")
    else:
        names = ["conv_im2col_pkg.sv", "cache/conv_sdp_ram.sv",
                 "cache/conv_next_use_predictor.sv", "conv_axi_span_reader.sv",
                 "cache/conv_read_cache.sv", "conv_im2col_frontend.sv"]
        parameters = [f"-GSIZE={tile}", f"-GLANES={window_lanes}", f"-GBUS_WIDTH={bus_width}",
                      "-GCACHE_SETS=128", "-GCACHE_POLICY=3"]
    sources = [(conv.parent / "dma" / name if name.startswith("cache/") else conv / name) for name in names
               if name != "vector_quant_params.sv" or (conv / name).exists()]
    if (repository / "rtl/common/regfile.v").exists():
        sources.append(repository / "rtl/common/regfile.v")
    if (repository / "rtl/common/add_equal.sv").exists():
        sources.append(repository / "rtl/common/add_equal.sv")
    if (repository / "rtl/common/onehot_check.sv").exists():
        sources.append(repository / "rtl/common/onehot_check.sv")
    identity = {str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources}
    tree, metadata = out / "design.tree.json", out / "design.meta.json"
    command = [executable, "--json-only", "--flatten", "--json-only-output", str(tree),
               "--json-only-meta-output", str(metadata), "--top-module", top,
               *parameters, "-DSYNTHESIS", "-DASIC_SYNTHESIS", "-Wno-fatal", *map(str, sources)]
    with (out / "elaboration.log").open("w") as log:
        subprocess.run(command, cwd=repository, stdout=log, stderr=subprocess.STDOUT, check=True)
    if any(hashlib.sha256((repository / name).read_bytes()).hexdigest() != digest
           for name, digest in identity.items()):
        raise RuntimeError("Sources changed during elaboration")
    nodes = list(walk(json.loads(tree.read_text())))
    by_id = {node["addr"]: node for node in nodes if "addr" in node}
    files = json.loads(metadata.read_text())["files"]

    def operand(value):
        while value["type"] in {"EXTEND", "EXTENDS"}:
            value = value["lhsp"][0]
        return {"type": value["type"], "bits": dtype_shape(value["dtypep"], by_id)["element_bits"],
                "variables": sorted({node["name"] for node in walk(value)
                                     if node.get("type") == "VARREF"})}

    multipliers = []
    for node in nodes:
        if node.get("type") not in {"MUL", "MULS"}:
            continue
        filename, coordinates = node["loc"].split(",", 1)
        source = str(Path(files[filename]["realpath"]).relative_to(repository))
        left, right = operand(node["lhsp"][0]), operand(node["rhsp"][0])
        variables = left["variables"] + right["variables"]
        category = "configuration_or_address"
        if source.endswith("vector_scalar_multiplier.sv"):
            category = "shared_scalar_partial"
        elif source.endswith("vector_pe.sv"):
            category = "vector_pe"
        elif (any(name.endswith("multiplier_a") for name in variables) or
              ({"vector_engine.q_accumulator", "vector_engine.q_multiplier"} <= set(variables))):
            category = "shared_quantization_softmax"
        elif left["type"] == "CONST" or right["type"] == "CONST":
            category = "constant_factor"
        multipliers.append({"operator": node["type"], "source": source,
                            "location": coordinates, "category": category,
                            "left": left, "right": right})
    storage = {}
    for node in nodes:
        if node.get("type") != "VAR":
            continue
        identifier = node["dtypep"]
        while by_id[identifier]["type"] == "REFDTYPE":
            identifier = by_id[identifier]["refDTypep"]
        if by_id[identifier]["type"] == "UNPACKARRAYDTYPE":
            storage[node["name"]] = dtype_shape(identifier, by_id)
    categories = dict(Counter(row["category"] for row in multipliers))
    if top == "vector_engine":
        if categories.get("vector_pe") != pes or categories.get("shared_scalar_partial") != 4:
            raise RuntimeError("Unexpected vector arithmetic resources: "+str(categories))
        for row in multipliers:
            if row["category"] == "shared_scalar_partial":
                if not (16 <= row["left"]["bits"] <= 17 and 16 <= row["right"]["bits"] <= 17):
                    raise RuntimeError("Unexpected shared multiplier partial-product width")
            expected = 16 if row["category"] == "vector_pe" else 32
            if row["category"] in {"vector_pe", "shared_quantization_softmax"}:
                if row["left"]["bits"] != expected or row["right"]["bits"] != expected:
                    raise RuntimeError("Unexpected multiplier operand width")
    return {"repository": str(repository), "top": top, "source_sha256": identity,
            "categories": categories, "multipliers": multipliers, "declared_arrays": storage,
            "tree_sha256": hashlib.sha256(tree.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--tile", type=int, default=16)
    parser.add_argument("--pes", type=int, default=8)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--window-lanes", type=int, choices=(4, 8, 16))
    parser.add_argument("--shared-quant", action="store_true")
    args = parser.parse_args()
    args.window_lanes = args.window_lanes or (16 if args.pes >= 16 else args.bus_width // 8)
    out = args.out.resolve()
    result = {"scope": "Elaborated RTL operators and declared arrays before synthesis; configuration and address expressions may be shared or simplified during synthesis.",
              "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "verilator": subprocess.check_output([args.verilator, "--version"], text=True).strip(),
              "tile": args.tile, "pes": args.pes, "bus_width": args.bus_width,
              "window_lanes": args.window_lanes, "shared_quant": args.shared_quant,
              "quantization_lanes": args.tile if args.shared_quant else 1, "designs": {}}
    repositories = {"current": ROOT}
    if args.reference:
        repositories["reference"] = args.reference.resolve()
    for label, repository in repositories.items():
        result["designs"][label] = {}
        for top in ("vector_engine", "conv_im2col_frontend"):
            record = inspect(repository, out / label / top, args.verilator, top, args.tile, args.pes,
                             args.bus_width, args.window_lanes, args.shared_quant)
            result["designs"][label][top] = record
            print(label, top, record["categories"], flush=True)
    if args.reference:
        old = result["designs"]["reference"]["vector_engine"]
        new = result["designs"]["current"]["vector_engine"]
        for name in ("input_buf", "rhs_buf", "bias_buf", "acc_buf", "result_buf"):
            key = "vector_engine." + name
            if old["declared_arrays"][key] != new["declared_arrays"][key]:
                raise RuntimeError("Vector data storage differs: " + key)
        def parameter_bits(record):
            arrays = record["declared_arrays"]
            selected = [shape for name, shape in arrays.items() if name in {
                "vector_engine.mult_buf", "vector_engine.shift_buf", "vector_engine.right_shift_buf"} or
                ("u_quant_params.g_bank[" in name and name.endswith(".u_regfile.mem"))]
            if not selected:
                raise RuntimeError("Vector quantization parameter storage was not found")
            return sum(math.prod(shape["dimensions"]) * shape["element_bits"] for shape in selected)
        if parameter_bits(old) != parameter_bits(new):
            raise RuntimeError("Vector quantization parameter storage capacity differs")
        result["quantization_parameter_storage_bits"] = parameter_bits(new)
        def weight_bits(record):
            arrays=record["declared_arrays"]
            selected=[shape for name,shape in arrays.items() if name=="vector_engine.weight_buf" or
                      ("g_weight_channel[" in name and name.endswith(".u_bank.data")) or
                      name in {"vector_engine.u_weights.u_storage.mem",
                               "vector_engine.g_private_weights.u_weights.u_storage.mem"}]
            if not selected:
                raise RuntimeError("Vector weight storage was not found")
            return sum(math.prod(shape["dimensions"])*shape["element_bits"] for shape in selected)
        old_bits,new_bits=weight_bits(old),weight_bits(new)
        if old_bits!=new_bits:
            raise RuntimeError("Vector weight storage capacity differs")
        result["weight_storage_bits"]=new_bits
    result["passed"] = True
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
