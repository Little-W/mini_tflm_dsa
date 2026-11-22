#!/usr/bin/env python3
"""解析工程内 RTL 模块依赖，返回无重复定义且 package 在前的源文件列表。"""
from __future__ import annotations

from pathlib import Path
import re


def _code(path: Path) -> str:
    text = path.read_text()
    # 保留字符串以外的标识符；注释和字符串不会引入模块依赖。
    return re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', " ", text, flags=re.S)


def with_dependencies(sources, root: Path):
    """补齐输入文件实例化的本地模块，并优先保留调用者提供的参考模块。"""
    root = Path(root).resolve()
    paths = list(dict.fromkeys(Path(path).resolve() for path in sources))
    catalog = {}
    definitions = {}
    code = {}
    candidates = sorted(path for path in (root / "rtl").rglob("*")
                        if path.suffix in (".v", ".sv") and "GV" not in path.relative_to(root / "rtl").parts)
    for path in candidates + paths:
        if path in code:
            continue
        text = _code(path) if path.suffix in (".v", ".sv") else ""
        code[path] = text
        definitions[path] = set(re.findall(r"\b(?:module|package)\s+(\w+)\b", text))
        if path.is_relative_to(root / "rtl"):
            for name in definitions[path]:
                if name in catalog and catalog[name] != path:
                    raise ValueError(f"Duplicate RTL definition {name}: {catalog[name]}, {path}")
                catalog[name] = path

    provided = set().union(*(definitions[path] for path in paths)) if paths else set()
    cursor = 0
    while cursor < len(paths):
        path = paths[cursor]
        cursor += 1
        referenced = set(re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", code[path]))
        for name in sorted(referenced & catalog.keys() - provided):
            if name in provided:
                continue
            dependency = catalog[name]
            if definitions[dependency] & provided:
                raise ValueError(f"Dependency file contains an existing definition: {dependency}")
            paths.append(dependency)
            provided.update(definitions[dependency])

    # 包之间的引用通过深度优先顺序处理，其余模块维持调用者给出的顺序。
    packages = {path for path in paths if re.search(r"\bpackage\s+\w+", code[path])}
    ordered = []
    visiting = set()
    visited = set()

    def visit(path):
        if path in visited:
            return
        if path in visiting:
            raise ValueError(f"Circular package dependency: {path}")
        visiting.add(path)
        for name in sorted(set(re.findall(r"\b(\w+)\s*::", code[path]))):
            dependency = catalog.get(name)
            if dependency in packages and dependency != path:
                visit(dependency)
        visiting.remove(path)
        visited.add(path)
        ordered.append(path)

    for path in paths:
        if path in packages:
            visit(path)
    return ordered + [path for path in paths if path not in packages]
