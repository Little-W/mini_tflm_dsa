#!/usr/bin/env python3
"""从 Git 版本导出具有独立模块及包定义的向量引擎参考设计。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "rev-parse", args.revision + "^{commit}"], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", revision, "rtl"], cwd=ROOT)
    reader = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))
    parts, names, hashes = [], {}, {}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
            source.extractall(root, filter="data")
        files = reader["with_dependencies"]([root / "rtl/npu/conv/vector_engine.sv"], root)
        for path in files:
            relative = str(path.relative_to(root))
            text = path.read_text()
            parts.append((relative, text))
            hashes[relative] = hashlib.sha256(text.encode()).hexdigest()
            code = re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S)
            for name in re.findall(r"\b(?:module|package)\s+(\w+)\b", code):
                if name != "vector_engine":
                    names[name] = "vector_ref__" + name
    identifiers = re.compile(r"\b(" + "|".join(sorted(names, key=len, reverse=True)) + r")\b")
    header_pattern = r"module vector_engine\s*#\(.*?\)\s*\(.*?\n\);"
    result = []
    for relative, text in parts:
        transformed = identifiers.sub(lambda match: names[match.group()], text)
        if relative == "rtl/npu/conv/vector_engine.sv":
            # 两个引擎连接同一公开接口，内部模块与包使用各自独立的定义。
            header = re.search(header_pattern, text, re.S)[0]
            transformed = re.sub(header_pattern, lambda _: header, transformed, count=1, flags=re.S)
        result.append(transformed)
    reference = "\n".join(result)
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(reference)
    manifest = {"revision": revision, "source_sha256": hashes,
                "definition_names": names,
                "reference_sha256": hashlib.sha256(reference.encode()).hexdigest()}
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"VECTOR_REFERENCE_READY files={len(parts)} definitions={len(names) + 1}")


if __name__ == "__main__":
    main()
