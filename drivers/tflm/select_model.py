#!/usr/bin/env python3
"""Select the TFLM application used by the project build."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'models' / 'registry.json'
SELECTION = ROOT / 'model_selection.mk'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='list available applications')
    parser.add_argument('--select', metavar='NAME', help='select an application')
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    names = list(registry)
    current = ''
    if SELECTION.exists():
        for line in SELECTION.read_text(encoding='utf-8').splitlines():
            if line.startswith('DEPLOY_MODEL :='):
                current = line.split(':=', 1)[1].strip()
                break
    if args.list or not args.select:
        for index, name in enumerate(names, 1):
            marker = '*' if name == current else ' '
            print(f'{marker} {index:2d}. {name:28s} {registry[name]["description"]}')
        if args.list:
            return
        value = input('选择模型编号或名称: ').strip()
        args.select = names[int(value) - 1] if value.isdigit() and 1 <= int(value) <= len(names) else value
    if args.select not in registry:
        parser.error(f'未知模型: {args.select}')
    model = registry[args.select]
    if not (ROOT / 'models' / model['directory']).is_dir():
        parser.error(f'模型目录不存在: {model["directory"]}')
    text = (f'DEPLOY_MODEL := {args.select}\n'
            f'DEPLOY_MODEL_DIR := drivers/tflm/models/{model["directory"]}\n'
            f'DEPLOY_TFLM_APP := {model["app"]}\n'
            f'DEPLOY_BUILD_TARGET := {model["build_target"]}\n'
            f'DEPLOY_CPU_MEM_WORDS := {model.get("cpu_mem_words", 65536)}\n')
    temporary = SELECTION.with_suffix('.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(SELECTION)
    print(f'当前模型: {args.select} ({model["description"]})')


if __name__ == '__main__':
    main()
