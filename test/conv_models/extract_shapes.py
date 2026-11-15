#!/usr/bin/env python3
"""Inventory actual regular INT8 CONV_2D layers from four bundled TFLite models.

Uses the repository's generated schema and the small flatbuffers package; does
not import TensorFlow, download a model, or run end-to-end model inference.
"""
from pathlib import Path
import argparse
import collections
import hashlib
import importlib.util
import json
import math

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TFLM = "drivers/tflm/tflm/tflite-micro/tensorflow/lite"
SCHEMA = ROOT / TFLM / "python/schema_py_generated.py"
MODELS = [
    ("mnist_cnn", "drivers/tflm/models/mnist_cnn/mnist_cnn_int8.tflite",
     "88df1be547cd6d8e73e56e88ed008514a5bd120bb840a5846cd3d4a573bf0589"),
    ("person_detect", "drivers/tflm/models/person_detection_reference/models/person_detect.tflite",
     "808cfdfc0cf3a6fa6f6fa26bfa379ea97c16d5db7334637766e39c3408502e9d"),
    ("justure_detect", "drivers/tflm/models/my_model/models/justure_detect.tflite",
     "9987bfec50a46580b84483a7bd36e658c14f2192c846cb9e932265dae60c7052"),
    ("mobilenet_v2", "drivers/tflm/tflm/tflite-micro/third_party/xtensa/examples/"
     "pytorch_to_tflite/mobilenet_v2_quantized_1x3x224x224.tflite",
     "2778683128d56fe4a3da6b8cdbbb00ec12663553f30a9b4fe927747ba637bb2f"),
]
RECOMMENDED = [
    ("mnist_cnn", 0, "Small-channel spatial Conv with symmetric padding"),
    ("mnist_cnn", 2, "Second real 3x3 layer with eight input channels"),
    ("justure_detect", 1, "Early regular 3x3 stride-2 layer; asymmetric SAME padding"),
    ("justure_detect", 7, "Regular 3x3 stride-2 with Cin=16"),
    ("justure_detect", 16, "Regular 3x3 stride-2 with Cin=32 and Cout=64"),
    ("justure_detect", 10, "Pointwise control with Cin=64"),
    ("person_detect", 6, "Real pointwise layer with Cin=32 and 24x24 spatial extent"),
    ("person_detect", 10, "Real pointwise layer with Cin=Cout=64"),
    ("mobilenet_v2", 32, "Pointwise projection with Cin=192"),
    ("mobilenet_v2", 52, "Unmodified pointwise expansion to Cout=576; output-channel replay"),
]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def enum_names(cls):
    return {v: k for k, v in vars(cls).items() if isinstance(v, int)}


def vector(obj, name, cast):
    return [cast(getattr(obj, name)(i)) for i in range(getattr(obj, name + "Length")())]


def quantization(tensor):
    q = tensor.Quantization()
    if q is None:
        return {"scale": [], "zero_point": [], "quantized_dimension": None}
    return {"scale": vector(q, "Scale", float),
            "zero_point": vector(q, "ZeroPoint", int),
            "quantized_dimension": int(q.QuantizedDimension())}


def round_away(value):
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def quantize_multiplier(scale):
    """Repository QuantizeMultiplier without TFLITE_SINGLE_ROUNDING saturation."""
    if scale == 0:
        return 0, 0
    assert math.isfinite(scale) and scale > 0
    fraction, shift = math.frexp(scale)
    multiplier = round_away(fraction * (1 << 31))
    if multiplier == (1 << 31):
        multiplier //= 2
        shift += 1
    if shift < -31:
        multiplier, shift = 0, 0
    assert 0 <= multiplier <= (1 << 31) - 1
    return multiplier, shift


def activation_bounds(name, scale, zero_point, np):
    # kernel_util.cc Quantize uses a float division, then TfLiteRound.
    def quantize(value):
        return zero_point + round_away(float(np.float32(value) / np.float32(scale)))
    if name == "RELU":
        return max(-128, quantize(0)), 127
    if name == "RELU6":
        return max(-128, quantize(0)), min(127, quantize(6))
    if name == "RELU_N1_TO_1":
        return max(-128, quantize(-1)), min(127, quantize(1))
    assert name == "NONE", f"Unsupported fused activation {name}"
    return -128, 127


def tensor_summary(model, graph, index, types):
    if index < 0:
        return None
    tensor = graph.Tensors(index)
    buf = model.Buffers(tensor.Buffer())
    constant = bytes(buf.DataAsNumpy()) if buf.DataLength() else b""
    return {"index": index, "name": (tensor.Name() or b"").decode("utf-8"),
            "shape": vector(tensor, "Shape", int), "dtype": types[tensor.Type()],
            "buffer_index": int(tensor.Buffer()), "constant_bytes": len(constant),
            "constant_sha256": sha256(constant) if constant else None,
            "quantization": quantization(tensor)}


def parse_model(schema, np, model_id, path, expected_sha):
    blob = (ROOT / path).read_bytes()
    assert blob[4:8] == b"TFL3", f"Not a TFLite file: {path}"
    assert sha256(blob) == expected_sha, f"Bundled model changed: {path}"
    model = schema.Model.GetRootAsModel(blob, 0)
    types, builtins = enum_names(schema.TensorType), enum_names(schema.BuiltinOperator)
    paddings, activations = enum_names(schema.Padding), enum_names(schema.ActivationFunctionType)
    inventory, layers, counts = [], [], collections.Counter()
    for sg in range(model.SubgraphsLength()):
        graph = model.Subgraphs(sg)
        for oi in range(graph.OperatorsLength()):
            op = graph.Operators(oi)
            opcode = model.OperatorCodes(op.OpcodeIndex())
            # Old TFLite files store their code only in the deprecated byte.
            code = max(opcode.BuiltinCode(), opcode.DeprecatedBuiltinCode())
            name = builtins.get(code, f"BUILTIN_{code}")
            counts[name] += 1
            inputs = [tensor_summary(model, graph, int(op.Inputs(i)), types)
                      for i in range(op.InputsLength())]
            outputs = [tensor_summary(model, graph, int(op.Outputs(i)), types)
                       for i in range(op.OutputsLength())]
            entry = {"subgraph_index": sg, "operator_index": oi,
                     "builtin_code": code, "operator": name,
                     "operator_version": int(opcode.Version()),
                     "inputs": [{k: t[k] for k in ("index", "name", "shape", "dtype")} if t else None for t in inputs],
                     "outputs": [{k: t[k] for k in ("index", "name", "shape", "dtype")} for t in outputs]}
            inventory.append(entry)
            if code != schema.BuiltinOperator.CONV_2D:
                continue
            inp, filt, out = inputs[0], inputs[1], outputs[0]
            bias = inputs[2] if len(inputs) > 2 else None
            opt = schema.Conv2DOptions()
            table = op.BuiltinOptions()
            assert op.BuiltinOptionsType() == schema.BuiltinOptions.Conv2DOptions
            opt.Init(table.Bytes, table.Pos)
            ish, fsh, osh = inp["shape"], filt["shape"], out["shape"]
            assert len(ish) == len(fsh) == len(osh) == 4
            assert all(v > 0 for v in ish + fsh + osh)
            assert ish[0] == osh[0] and fsh[0] == osh[3] and ish[3] % fsh[3] == 0
            groups = ish[3] // fsh[3]
            assert osh[3] % groups == 0
            sh, sw = int(opt.StrideH()), int(opt.StrideW())
            dh, dw = int(opt.DilationHFactor()), int(opt.DilationWFactor())
            mode = paddings[opt.Padding()]
            eff_h, eff_w = (fsh[1] - 1) * dh + 1, (fsh[2] - 1) * dw + 1
            assert min(sh, sw, dh, dw) > 0
            if mode == "SAME":
                expected_hw = [(ish[1] + sh - 1) // sh, (ish[2] + sw - 1) // sw]
                total_h = max(0, (osh[1] - 1) * sh + eff_h - ish[1])
                total_w = max(0, (osh[2] - 1) * sw + eff_w - ish[2])
            else:
                assert mode == "VALID"
                expected_hw = [(ish[1] + sh - eff_h) // sh, (ish[2] + sw - eff_w) // sw]
                total_h = total_w = 0
            assert expected_hw == osh[1:3], f"Shape/options mismatch: {model_id} op {oi}"
            padding = {"mode": mode, "top": total_h // 2, "left": total_w // 2,
                       "bottom": total_h - total_h // 2, "right": total_w - total_w // 2}
            layer = {"layer_id": f"{model_id}:sg{sg}:op{oi}", "model_id": model_id,
                     "model_path": path, "model_sha256": expected_sha,
                     "subgraph_index": sg, "operator_index": oi,
                     "operator": name, "builtin_code": code, "regular_conv": True,
                     "operator_version": int(opcode.Version()),
                     "input_shape": ish, "filter_shape": fsh, "output_shape": osh,
                     "input_layout": "NHWC", "filter_layout": "OHWI", "output_layout": "NHWC",
                     "input_dtype": inp["dtype"], "filter_dtype": filt["dtype"], "output_dtype": out["dtype"],
                     "stride_hw": [sh, sw], "dilation_hw": [dh, dw], "padding": padding,
                     "groups": groups, "group_c": fsh[3], "reduction_length": math.prod(fsh[1:]),
                     "input_bytes": math.prod(ish), "filter_bytes": math.prod(fsh), "output_bytes": math.prod(osh),
                     "macs": math.prod(osh) * math.prod(fsh[1:]),
                     "fused_activation": activations[opt.FusedActivationFunction()],
                     "tensors": {"input": inp, "filter": filt, "bias": bias, "output": out}}
            int8 = all(t["dtype"] == "INT8" for t in (inp, filt, out))
            layer["regular_int8"] = int8
            if int8:
                iq, wq, oq = (t["quantization"] for t in (inp, filt, out))
                assert len(iq["scale"]) == len(iq["zero_point"]) == len(oq["scale"]) == len(oq["zero_point"]) == 1
                assert len(wq["scale"]) in (1, osh[3]) and all(v == 0 for v in wq["zero_point"])
                assert len(wq["scale"]) == 1 or wq["quantized_dimension"] == 0
                scale_i, scale_o = iq["scale"][0], oq["scale"][0]
                assert scale_i > 0 and scale_o > 0 and all(v > 0 for v in wq["scale"])
                effective = [scale_i * wq["scale"][i if len(wq["scale"]) > 1 else 0] / scale_o for i in range(osh[3])]
                quant = [quantize_multiplier(v) for v in effective]
                act_min, act_max = activation_bounds(layer["fused_activation"], scale_o, oq["zero_point"][0], np)
                layer.update(input_offset=-iq["zero_point"][0], output_offset=oq["zero_point"][0],
                             activation_min=act_min, activation_max=act_max,
                             quantization={"input": iq, "filter": wq, "output": oq,
                                           "bias": bias["quantization"] if bias else None,
                                           "effective_scales": effective,
                                           "multipliers": [v[0] for v in quant],
                                           "shifts": [v[1] for v in quant]})
            reasons = []
            if not int8: reasons.append("not INT8 input/filter/output")
            if layer["input_bytes"] > 65536: reasons.append("input exceeds 64 KiB arena")
            if layer["filter_bytes"] > 65536: reasons.append("filter exceeds 64 KiB arena")
            if layer["output_bytes"] > 262141: reasons.append("output exceeds available 512 KiB test RAM layout")
            if layer["reduction_length"] > 65535: reasons.append("reduction exceeds driver u16 limit")
            layer["rtl_arena_eligible"] = not reasons
            layer["rtl_arena_exclusion_reasons"] = reasons
            layers.append(layer)
    return {"model_id": model_id, "path": path, "sha256": expected_sha,
            "file_bytes": len(blob), "schema_version": int(model.Version()),
            "subgraphs": int(model.SubgraphsLength()), "operator_counts": dict(sorted(counts.items())),
            "regular_conv2d_count": len(layers), "regular_int8_count": sum(l["regular_int8"] for l in layers),
            "depthwise_conv2d_excluded_count": counts["DEPTHWISE_CONV_2D"],
            "operator_inventory": inventory}, layers


def extract_catalogue():
    """Read bundled TFLite files now; never consume a precomputed catalogue."""
    try:
        import flatbuffers
        import numpy as np
    except ImportError as exc:
        raise SystemExit("Install small dependencies: python3 -m pip install flatbuffers==25.2.10 numpy") from exc
    spec = importlib.util.spec_from_file_location("repository_tflite_schema", SCHEMA)
    schema = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema)
    models, layers = [], []
    for model_id, path, digest in MODELS:
        model, parsed = parse_model(schema, np, model_id, path, digest)
        models.append(model)
        layers.extend(parsed)
    recommended = []
    for model_id, index, reason in RECOMMENDED:
        layer_id = f"{model_id}:sg0:op{index}"
        layer = next(v for v in layers if v["layer_id"] == layer_id)
        assert layer["regular_int8"] and layer["rtl_arena_eligible"]
        layer["selection_reason"] = reason
        recommended.append(layer_id)
    source_paths = [Path(__file__).resolve(), SCHEMA,
                    ROOT / TFLM / "kernels/padding.h",
                    ROOT / TFLM / "kernels/kernel_util.cc",
                    ROOT / TFLM / "kernels/internal/quantization_util.cc"]
    result = {"format_version": 1,
              "scope": "Complete regular-CONV_2D inventory of the four listed bundled models; not a scan of every repository model",
              "verification_level": "TFLite metadata extraction only; no full-network inference or RTL execution by this script",
              "dependencies": {"flatbuffers": flatbuffers.__version__, "numpy": np.__version__},
              "source_sha256": {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in source_paths},
              "layout_contract": "Input/output NHWC, regular CONV_2D filter OHWI; DEPTHWISE_CONV_2D excluded by opcode",
              "quantization_derivation": "effective=input_scale*filter_scale[channel]/output_scale; repository double-rounding QuantizeMultiplier contract; fused activation range follows float32 Quantize",
              "data_policy": "Model shapes/options/quantization are extracted exactly. RTL consumers may generate synthetic inputs/weights/bias and must label that choice; this inventory does not imply model accuracy testing.",
              "rtl_arena_assumption": {"input_base": 65536, "input_capacity": 65536,
                                       "filter_base": 131072, "filter_capacity": 65536,
                                       "output_base": 262147, "ram_bytes": 524288},
              "models": models, "layers": layers,
              "recommended_layer_ids": recommended,
              "summary": {"models": len(models), "regular_conv2d": len(layers),
                          "regular_int8": sum(l["regular_int8"] for l in layers),
                          "depthwise_excluded": sum(m["depthwise_conv2d_excluded_count"] for m in models),
                          "rtl_arena_eligible": sum(l["rtl_arena_eligible"] for l in layers),
                          "recommended": len(recommended)}}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "build/conv_models/models.json")
    args = ap.parse_args()
    result = extract_catalogue()
    layers = result["layers"]
    recommended = result["recommended_layer_ids"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["summary"], sort_keys=True))
    for layer_id in recommended:
        l = next(v for v in layers if v["layer_id"] == layer_id)
        print(layer_id, "input", l["input_shape"], "filter", l["filter_shape"], "output", l["output_shape"],
              "stride", l["stride_hw"], "padding", l["padding"], "offset", l["input_offset"])
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
