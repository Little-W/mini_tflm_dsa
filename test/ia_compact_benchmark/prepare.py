#!/usr/bin/env python3
"""从模型实测张量和随模型提供的图像提取 GEMM 操作数。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/model_benchmark"))
from verify_integer_graph import load_schema, limits, requant
sys.path.insert(0, str(ROOT / "test/conv_models"))
from extract_shapes import MODELS, parse_model

SELECTED = {
    "mobilenet_v1_vww": {4, 10, 24},
    "resnet8_cifar10": {1, 9},
    "mobilenet_v2": {32, 52},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def checked_payload(path, record):
    data = path.read_bytes()
    if len(data) != record["bytes"] or digest(data) != record["sha256"]:
        raise ValueError(f"Source tensor differs from its manifest: {path}")
    return np.frombuffer(data, dtype=record["dtype"]).reshape(record["shape"])


def lower_conv(source, weights, output_shape, options, zero_point):
    """按 NHWC/OHWI 顺序保留全部输出位置、通道和归约元素。"""
    batch, ih, iw, channels = source.shape
    _, oh, ow, columns = output_shape
    _, kh, kw, wc = weights.shape
    if wc != channels:
        raise ValueError("Grouped convolution requires an explicit group expansion")
    sh, sw = options["stride_h"], options["stride_w"]
    dh, dw = options.get("dilation_h_factor", 1), options.get("dilation_w_factor", 1)
    ph = max(0, (oh - 1) * sh + (kh - 1) * dh + 1 - ih) // 2 if options["padding"] == "SAME" else 0
    pw = max(0, (ow - 1) * sw + (kw - 1) * dw + 1 - iw) // 2 if options["padding"] == "SAME" else 0
    matrix = np.full((batch, oh, ow, kh, kw, channels), zero_point, dtype=np.int8)
    for ky in range(kh):
        yy = np.arange(oh) * sh + ky * dh - ph
        for kx in range(kw):
            xx = np.arange(ow) * sw + kx * dw - pw
            valid = ((yy[:, None] >= 0) & (yy[:, None] < ih) &
                     (xx[None, :] >= 0) & (xx[None, :] < iw))[None, :, :, None]
            pixels = source[:, np.clip(yy, 0, ih - 1)[:, None], np.clip(xx, 0, iw - 1)[None, :], :]
            matrix[:, :, :, ky, kx, :] = np.where(valid, pixels, zero_point)
    return matrix.reshape(-1, kh * kw * channels), weights.reshape(columns, -1)


def storage_statistics(matrix, offset):
    """按实际 16×16 存储块统计范围，并验证有偏移的 INT16 可逆恢复。"""
    adjusted = matrix.astype(np.int16) + offset
    encoded = adjusted - offset
    decoded = encoded.astype(np.int8).astype(np.int16) + offset
    if not np.array_equal(adjusted, decoded):
        raise ValueError("IA encode/decode changed a value")
    rows, depth = matrix.shape
    padded = np.full((((rows + 15) // 16) * 16, ((depth + 15) // 16) * 16),
                     -offset, dtype=np.int16)
    padded[:rows, :depth] = matrix
    blocks = padded.reshape(-1, 16, padded.shape[1] // 16, 16).transpose(0, 2, 1, 3).reshape(-1, 256)
    span = blocks.max(axis=1) - blocks.min(axis=1)
    eligible = -127 <= offset <= 128
    return dict(elements=int(matrix.size), compact_offset=int(offset),
                raw_min=int(matrix.min()), raw_max=int(matrix.max()),
                adjusted_min=int(adjusted.min()), adjusted_max=int(adjusted.max()),
                source_bits=8, wide_storage_bytes=int(matrix.size * 2),
                compact_storage_bytes=int(matrix.size if eligible else matrix.size * 2),
                eligible_elements=int(matrix.size if eligible else 0),
                block_count=int(span.size), block_span_min=int(span.min()),
                block_span_median=float(np.median(span)), block_span_max=int(span.max()),
                blocks_span_above_127=int((span > 127).sum()),
                restore_comparisons=int(matrix.size), restore_passed=True)


def emit_case(out, model_id, sample, node, lhs, rhs, bias, parameters,
              input_offset, output_offset, activation, provenance, golden=None):
    stats = storage_statistics(lhs, input_offset)
    item = dict(model=model_id, sample=sample, operator_index=int(node),
                m=int(lhs.shape[0]), k=int(lhs.shape[1]), n=int(rhs.shape[0]), **stats)
    if node not in SELECTED[model_id]:
        return None, item
    accum = (lhs.astype(np.int64) + input_offset) @ rhs.astype(np.int64).T + bias
    if accum.min() < -(1 << 31) or accum.max() >= (1 << 31):
        raise ValueError("GEMM accumulators exceed INT32")
    output = np.clip(requant(accum, parameters) + output_offset, *activation).astype(np.int8)
    if golden is not None and not np.array_equal(output.reshape(golden.shape), golden):
        raise ValueError(f"Captured reference differs: {model_id} sample {sample} node {node}")
    name = f"{model_id}_sample{sample:04d}_op{node:03d}"
    target = out / name
    target.mkdir(parents=True, exist_ok=True)
    tensors = {}
    for key, value in dict(lhs=lhs, rhs=rhs, bias=np.asarray(bias, dtype="<i4"),
                           multipliers=np.asarray(parameters["multipliers"], dtype="<i4"),
                           shifts=np.asarray(parameters["shifts"], dtype="<i4"),
                           accumulators=accum.astype("<i4"), output=output).items():
        value = np.ascontiguousarray(value)
        payload = value.tobytes()
        path = target / (key + ".bin")
        path.write_bytes(payload)
        tensors[key] = dict(path=path.name, bytes=len(payload), sha256=digest(payload),
                            dtype=value.dtype.str, shape=list(value.shape))
    record = dict(name=name, **item, input_offset=int(input_offset),
                  output_offset=int(output_offset), activation_min=int(activation[0]),
                  activation_max=int(activation[1]), tensors=tensors, provenance=provenance,
                  reference="INT64 NumPy GEMM, INT32 range check, Q31 nearest-even requantization",
                  captured_output_checked=golden is not None)
    write_json(target / "case.json", record)
    return dict(name=name, manifest=str((target / "case.json").relative_to(out)),
                manifest_sha256=digest((target / "case.json").read_bytes())), item


def captured_cases(root, out, schema):
    cases, statistics = [], []
    for path in sorted(root.glob("*/????/trace/case.json")):
        record = json.loads(path.read_text())
        model_id = record["model_id"]
        if model_id not in ("mobilenet_v1_vww", "resnet8_cifar10"):
            continue
        directory = path.parent
        model_bytes = (directory / "model_after.bin").read_bytes()
        if digest(model_bytes) != record["model"]["sha256"]:
            raise ValueError("Captured model differs from its manifest")
        model = schema.Model.GetRootAsModel(model_bytes, 0)
        graph = model.Subgraphs(0)
        metadata = {t["index"]: t for t in record["graph"]["tensors"]}
        tensors = {}
        for index, tensor in metadata.items():
            buffer = model.Buffers(graph.Tensors(index).Buffer())
            if buffer.DataLength():
                tensors[index] = np.frombuffer(buffer.DataAsNumpy().tobytes(), dtype=tensor["dtype"]).reshape(tensor["shape"])
        sample = record["sample"]
        inputs = sample["input"]
        tensors[inputs["tensor_index"]] = checked_payload(directory / "input_after.bin", inputs)
        outputs = {n["operator_index"]: n for n in sample["nodes"]}
        for node in record["graph"]["nodes"]:
            expected = outputs[node["index"]]
            golden = checked_payload(directory / "tensors" / f"tensor_{node['index']}.bin", expected)
            indices = node["inputs"]
            if node["op"] in ("CONV_2D", "FULLY_CONNECTED"):
                source, weights = tensors[indices[0]], tensors[indices[1]]
                zp = metadata[indices[0]]["zero_points"][0]
                if any(metadata[indices[1]]["zero_points"]):
                    raise ValueError("The selected GEMM requires symmetric weights")
                if node["op"] == "CONV_2D":
                    lhs, rhs = lower_conv(source, weights, golden.shape, node["options"], zp)
                else:
                    lhs, rhs = source.reshape(-1, weights.shape[-1]), weights
                bias = tensors[indices[2]].astype(np.int64) if len(indices) > 2 and indices[2] >= 0 else np.zeros(rhs.shape[0], dtype=np.int64)
                output_meta = metadata[node["outputs"][0]]
                entry, stat = emit_case(out, model_id, record["sample_index"], node["index"],
                    lhs, rhs, bias, expected["integer_parameters"], -zp,
                    output_meta["zero_points"][0],
                    limits(output_meta, node["options"].get("fused_activation_function", "NONE")),
                    dict(kind="recorded_model_inference", model=record["model"],
                         input_sha256=inputs["sha256"], case_sha256=digest(path.read_bytes()),
                         activation_sha256=digest(source.tobytes()),
                         output_sha256=expected["sha256"]), golden)
                statistics.append(stat)
                if entry:
                    cases.append(entry)
            tensors[node["outputs"][0]] = golden
    return cases, statistics


def mobilenet_v2_cases(out, schema):
    from ai_edge_litert.interpreter import Interpreter, OpResolverType
    model_id, relative, expected_sha = next(item for item in MODELS if item[0] == "mobilenet_v2")
    model_path = ROOT / relative
    image_path = model_path.parent / "pytorch_images_dog_jpg.cc"
    image_text = image_path.read_text()
    declaration = re.search(r"g_pytorch_images_dog_jpg_data\[\]\s*=\s*\{(.*?)\};", image_text, re.S)
    if declaration is None:
        raise ValueError("Bundled quantized image array is missing")
    image = bytes(int(token, 16) for token in re.findall(r"0x([0-9a-fA-F]{2})", declaration[1]))
    declared_length = int(re.search(r"g_pytorch_images_dog_jpg_len\s*=\s*(\d+)", image_text)[1])
    if len(image) != declared_length:
        raise ValueError("Bundled input length differs from its declaration")
    interpreter = Interpreter(model_path=str(model_path), num_threads=1,
        experimental_preserve_all_tensors=True, experimental_op_resolver_type=OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    input_meta = interpreter.get_input_details()[0]
    interpreter.set_tensor(input_meta["index"], np.frombuffer(image, dtype=np.int8).reshape(input_meta["shape"]))
    interpreter.invoke()
    _, layers = parse_model(schema, np, model_id, relative, expected_sha)
    cases, statistics = [], []
    for layer in layers:
        if not layer["regular_int8"]:
            continue
        source = interpreter.get_tensor(layer["tensors"]["input"]["index"])
        weights = interpreter.get_tensor(layer["tensors"]["filter"]["index"])
        bias = interpreter.get_tensor(layer["tensors"]["bias"]["index"]).astype(np.int64)
        options = dict(stride_h=layer["stride_hw"][0], stride_w=layer["stride_hw"][1],
                       dilation_h_factor=layer["dilation_hw"][0], dilation_w_factor=layer["dilation_hw"][1],
                       padding=layer["padding"]["mode"])
        lhs, rhs = lower_conv(source, weights, layer["output_shape"], options, -layer["input_offset"])
        entry, stat = emit_case(out, model_id, 0, layer["operator_index"], lhs, rhs, bias,
            layer["quantization"], layer["input_offset"], layer["output_offset"],
            (layer["activation_min"], layer["activation_max"]),
            dict(kind="bundled_model_and_image_inference", model_path=relative, model_sha256=expected_sha,
                 input_path=str(image_path.relative_to(ROOT)), input_file_sha256=digest(image_path.read_bytes()),
                 input_sha256=digest(image), activation_sha256=digest(source.tobytes()),
                 inference_engine="ai-edge-litert 2.4.0 BUILTIN_REF"))
        statistics.append(stat)
        if entry:
            cases.append(entry)
    return cases, statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    schema = load_schema()
    args.out.mkdir(parents=True, exist_ok=True)
    captured, captured_stats = captured_cases(args.captures, args.out, schema)
    mobilenet, mobilenet_stats = mobilenet_v2_cases(args.out, schema)
    cases, statistics = captured + mobilenet, captured_stats + mobilenet_stats
    expected = sum(2 * len(SELECTED[name]) for name in ("mobilenet_v1_vww", "resnet8_cifar10")) + len(SELECTED["mobilenet_v2"])
    if len(cases) != expected:
        raise ValueError(f"Expected {expected} selected GEMMs, obtained {len(cases)}")
    write_json(args.out / "corpus.json", dict(cases=cases, selection={k: sorted(v) for k, v in SELECTED.items()},
        statistics=statistics, total_elements=sum(s["elements"] for s in statistics),
        eligible_elements=sum(s["eligible_elements"] for s in statistics),
        reference_checks=sum(s["restore_comparisons"] for s in statistics)))
    print(json.dumps(dict(cases=len(cases), operator_inputs=len(statistics),
                         elements=sum(s["elements"] for s in statistics), passed=True)))


if __name__ == "__main__":
    main()
