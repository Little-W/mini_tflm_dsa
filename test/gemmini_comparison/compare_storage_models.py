#!/usr/bin/env python3
"""汇总已核验的完整推理与逐层结果，保持各次实测计时独立。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

from verify_storage_models import MODELS, require, verify_complete_models


LABELS = {
    "mnist_cnn": "MNIST CNN",
    "mobilenet_v1_vww": "MobileNetV1 VWW",
    "resnet8_cifar10": "ResNet-8 CIFAR-10",
    "ds_cnn_kws": "DS-CNN KWS",
}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                             else value for key, value in row.items()})


def summarize(npu, prepared, variants):
    platforms = ("npu", *variants)
    runs, model_rows, model_samples, layer_samples, layer_rows = [], [], [], [], []
    source_files = {}
    for model in MODELS:
        manifest_path = prepared / model / "manifest.json"
        manifest = read(manifest_path)
        source_files[str(manifest_path)] = digest(manifest_path)
        grouped = defaultdict(list)
        for sample in (0, 1):
            traced = {}
            sample_perf = {}
            identities = set()
            for platform in platforms:
                for kind in ("perf", "trace"):
                    if platform == "npu":
                        directory = npu / "results/cases" / model / f"sample_{sample:04d}" / f"{kind}_63"
                    else:
                        directory = Path(variants[platform]["directory"]) / model / f"{sample:04d}" / kind
                    path = directory / "result.json"
                    record = read(path)
                    require(record["passed"] and all(record["checks"].values()), "Model execution must pass")
                    source_files[str(path)] = digest(path)
                    identities.add((record["model"]["sha256"], record["input_sha256"],
                                    record["output_comparison"]["actual_sha256"]))
                    result = record["result"]
                    run = dict(platform=platform, model=model, sample=sample, kind=kind,
                        invoke_cycles=result["invoke_cycles"], initialization_cycles=result["init_cycles"],
                        planning_cycles=result.get("planning_cycles", 0),
                        accelerator_busy_cycles=record["network"]["npu_busy_cycles"],
                        read_bytes=record["network"]["npu_read_bytes"],
                        write_bytes=record["network"]["npu_write_bytes"],
                        arena_used_bytes=result["arena_used_bytes"],
                        firmware_sha256=record["firmware_elf_sha256"],
                        simulator_sha256=record["simulator"]["simulator_sha256"],
                        result_path=str(path), output_exact=True)
                    run["initialization_and_invoke_cycles"] = run["initialization_cycles"] + run["invoke_cycles"]
                    runs.append(run)
                    if kind == "perf":
                        grouped[platform].append(run)
                        sample_perf[platform] = run
                    else:
                        traced[platform] = record
            require(len(identities) == 1, "Models, inputs and outputs differ between platforms")
            fastest = min(variants, key=lambda name: (sample_perf[name]['invoke_cycles'], name))
            fastest_startup = min(variants, key=lambda name: (sample_perf[name]['initialization_and_invoke_cycles'], name))
            npu_cycles, gemmini_cycles = sample_perf['npu']['invoke_cycles'], sample_perf[fastest]['invoke_cycles']
            npu_startup = sample_perf['npu']['initialization_and_invoke_cycles']
            gemmini_startup = sample_perf[fastest_startup]['initialization_and_invoke_cycles']
            model_samples.append(dict(model=model, sample=sample, selected_gemmini_variant=fastest,
                gemmini_over_npu=gemmini_cycles / npu_cycles, target_met=6 * npu_cycles <= 5 * gemmini_cycles,
                fastest_startup_gemmini_variant=fastest_startup,
                startup_gemmini_over_npu=gemmini_startup / npu_startup,
                **{platform: {key: values[key] for key in ('invoke_cycles', 'initialization_cycles',
                    'planning_cycles', 'initialization_and_invoke_cycles', 'arena_used_bytes')}
                   for platform, values in sample_perf.items()}))
            nodes = manifest["graph"]["nodes"]
            expected_tensors = {row["descriptor"]["ordinal"]: row["comparison"]["expected_sha256"]
                                for row in traced["npu"]["trace"]}
            for platform, record in traced.items():
                require([row["index"] for row in record["layers"]] == [row["index"] for row in nodes],
                        "Model operator order differs")
                require({row["descriptor"]["ordinal"]: row["comparison"]["actual_sha256"]
                         for row in record["trace"]} == expected_tensors, "Intermediate tensors differ")
            for ordinal, node in enumerate(nodes):
                row = dict(model=model, sample=sample, index=node["index"], op=node["op"],
                           input_shapes=node["input_shapes"], output_shapes=node["output_shapes"],
                           options=node.get("options", {}), output_exact=True)
                for platform, record in traced.items():
                    counter = record["layers"][ordinal]
                    row[platform] = dict(cycles=counter["cycles"],
                        accelerator_busy_cycles=counter["npu_busy_cycles"],
                        read_bytes=counter["npu_read_bytes"], write_bytes=counter["npu_write_bytes"],
                        cpu_instruction_reads=counter["cpu_instruction_reads"],
                        cpu_data_reads=counter["cpu_data_reads"],
                        cpu_mmio_reads=counter["cpu_mmio_reads"],
                        cpu_mmio_write_bytes=counter["cpu_mmio_write_bytes"])
                    if platform in variants:
                        row[platform].update(execution_path=counter["execution_path"],
                            commands=counter["commands"], im2col_requests=counter["im2col_requests"],
                            im2col_responses=counter["im2col_responses"])
                layer_samples.append(row)
        row = dict(model=model, label=LABELS[model], samples=2)
        for platform, records in grouped.items():
            require(len(records) == 2, "Each model requires both input samples")
            row[platform] = {key: mean(record[key] for record in records) for key in (
                "invoke_cycles", "initialization_cycles", "planning_cycles", "accelerator_busy_cycles",
                "initialization_and_invoke_cycles", "read_bytes", "write_bytes", "arena_used_bytes")}
            row[platform]["elapsed_outside_accelerator_busy_cycles"] = (
                row[platform]["invoke_cycles"] - row[platform]["accelerator_busy_cycles"])
            row[platform]["milliseconds_at_100mhz"] = row[platform]["invoke_cycles"] / 100000
        selected = min(variants, key=lambda name: (row[name]["invoke_cycles"], name))
        row["selected_gemmini_variant"] = selected
        row["gemmini_over_npu"] = row[selected]["invoke_cycles"] / row["npu"]["invoke_cycles"]
        samples_for_model = [item for item in model_samples if item['model'] == model]
        row['minimum_sample_speedup'] = min(item['gemmini_over_npu'] for item in samples_for_model)
        row['all_samples_at_least_1_2x'] = all(item['target_met'] for item in samples_for_model)
        row['minimum_startup_speedup'] = min(item['startup_gemmini_over_npu'] for item in samples_for_model)
        model_rows.append(row)
    lookup = {row["model"]: row for row in model_rows}
    for model in MODELS:
        for index in sorted({row["index"] for row in layer_samples if row["model"] == model}):
            observations = [row for row in layer_samples if (row["model"], row["index"]) == (model, index)]
            require(len(observations) == 2, "Each layer requires both input samples")
            first = observations[0]
            row = {key: first[key] for key in ("model", "index", "op", "input_shapes", "output_shapes", "options")}
            for platform in ("npu", *variants):
                fields = observations[0][platform]
                row[platform] = {key: mean(item[platform][key] for item in observations)
                                 for key, value in fields.items() if isinstance(value, (int, float))}
                if platform in variants:
                    require(len({item[platform]["execution_path"] for item in observations}) == 1,
                            "A static model layer must use the same execution path on both inputs")
                    row[platform]["execution_path"] = first[platform]["execution_path"]
            selected = lookup[model]["selected_gemmini_variant"]
            row.update(selected_gemmini_variant=selected,
                       gemmini_over_npu=row[selected]["cycles"] / row["npu"]["cycles"], output_exact=True)
            layer_rows.append(row)
    categories = []
    for op in sorted({row["op"] for row in layer_rows}):
        subset = [row for row in layer_rows if row["op"] == op]
        row = dict(op=op, layers=len(subset))
        for platform in ("npu", *variants, "selected_gemmini"):
            row[platform] = {field: sum(item[item["selected_gemmini_variant"] if platform == "selected_gemmini"
                                             else platform][field] for item in subset)
                             for field in ("cycles", "accelerator_busy_cycles", "read_bytes", "write_bytes")}
        row["gemmini_over_npu"] = row["selected_gemmini"]["cycles"] / row["npu"]["cycles"]
        categories.append(row)
    aggregate = {}
    for platform in (*platforms, "selected_gemmini"):
        aggregate[platform] = {field: sum(row[row["selected_gemmini_variant"] if platform == "selected_gemmini"
                                               else platform][field] for row in model_rows)
                              for field in ("invoke_cycles", "initialization_cycles", "planning_cycles",
                                            "accelerator_busy_cycles", "initialization_and_invoke_cycles",
                                            "read_bytes", "write_bytes")}
    aggregate["gemmini_over_npu"] = aggregate["selected_gemmini"]["invoke_cycles"] / aggregate["npu"]["invoke_cycles"]
    paths = {platform: dict(Counter(row[platform]["execution_path"] for row in layer_rows)) for platform in variants}
    return dict(passed=True, measurement="两个输入的完整 MicroInterpreter::Invoke 平均周期；初始化单独记录",
        selection="每个模型选取完整实测推理最快的 Gemmini 固件，保留该次整网计时",
        layer_measurement="独立逐层记录固件，包含命令提交、加速器等待和软件处理",
        source_files=source_files, variants=variants, models=model_rows, model_samples=model_samples,
        model_target_rule='逐个输入使用 6*NPU_Invoke<=5*Gemmini_Invoke，Gemmini 为该输入完整推理最快固件',
        startup_measurement='初始化加首个 Invoke，按启动总时间最快的完整 Gemmini 固件单独比较',
        aggregate=aggregate, runs=runs,
        layers=layer_rows, layer_samples=layer_samples, operator_categories=categories,
        actual_execution_paths=paths, model_nodes=len(layer_rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--npu", type=Path, required=True)
    parser.add_argument("--npu-capacity", type=Path, required=True)
    parser.add_argument("--gemmini-capacity", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--gemmini-sim", type=Path, required=True)
    parser.add_argument("--gemmini-variant", action="append", required=True,
                        metavar="NAME=DIRECTORY=SOURCE=POLICY")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
    args = parser.parse_args()
    variants = {}
    for value in args.gemmini_variant:
        name, directory, source, policy = value.split("=", 3)
        require(name not in variants and name not in ("software", "npu"), "Duplicate platform name")
        variants[name] = dict(directory=str(Path(directory).resolve()), source=str(Path(source).resolve()), policy=policy)
    npu, prepared, repo = args.npu.resolve(), args.prepared.resolve(), args.repo.resolve()
    out = args.out.resolve() if args.out else npu / "comparison"
    out.mkdir(parents=True, exist_ok=True)
    verification = verify_complete_models(repo, npu, args.gemmini_sim.resolve(), variants,
        prepared, data_root=npu.parent, path_mappings=[item.split("=", 1) for item in args.map],
        npu_capacity=args.npu_capacity, gemmini_capacity=args.gemmini_capacity)
    require(verification["passed"] and verification["complete_suite"], "Full verification is required")
    result = summarize(npu, prepared, variants)
    result["verification"] = {key: value for key, value in verification.items() if key != "files"}
    result["generator_sha256"] = digest(__file__)
    result["verification_program_sha256"] = digest(Path(__file__).with_name("verify_storage_models.py"))
    write_json(out / "model_verification.json", verification)
    write_json(out / "models.json", result)
    model_csv = []
    for row in result["models"]:
        entry = dict(model=row["model"], selected_gemmini_variant=row["selected_gemmini_variant"])
        for platform in ("npu", *variants):
            entry.update({f"{platform}_{key}": value for key, value in row[platform].items()})
        entry.update({key: row[key] for key in ('gemmini_over_npu', 'minimum_sample_speedup',
                                               'all_samples_at_least_1_2x', 'minimum_startup_speedup')})
        model_csv.append(entry)
    write_csv(out / "models.csv", model_csv)
    write_csv(out / 'runs.csv', result['runs'])
    sample_csv = []
    for row in result['model_samples']:
        entry = {key: value for key, value in row.items() if key not in ('npu', *variants)}
        for platform in ('npu', *variants):
            entry.update({f'{platform}_{key}': value for key, value in row[platform].items()})
        sample_csv.append(entry)
    write_csv(out / 'model_samples.csv', sample_csv)
    for key, name in (("layers", "layers.csv"), ("layer_samples", "layer_samples.csv")):
        values = []
        for row in result[key]:
            entry = {k: row[k] for k in ("model", "index", "op", "output_shapes")}
            if "sample" in row:
                entry["sample"] = row["sample"]
            for platform in ("npu", *variants):
                entry.update({f"{platform}_{k}": v for k, v in row[platform].items()})
            entry["output_exact"] = row["output_exact"]
            values.append(entry)
        write_csv(out / name, values)
    print(json.dumps(dict(passed=True, verified_runs=verification["checked_runs"],
                         verified_tensors=verification["checked_intermediate_tensors"],
                         aggregate=result["aggregate"], out=str(out)), ensure_ascii=False))


if __name__ == "__main__":
    main()
