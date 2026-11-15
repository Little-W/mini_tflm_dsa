#!/usr/bin/env python3
"""Validate and copy the four trained models and nearest-even tensor references.

The benchmark data package records model origins, hashes, graph geometry,
quantization parameters, real input provenance and every operator output.
This tool verifies all referenced bytes before copying a prepared package.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

MODELS = ('mnist_cnn', 'mobilenet_v1_vww', 'ds_cnn_kws', 'resnet8_cifar10')
MODEL_SHA256 = {
    'mnist_cnn': '88df1be547cd6d8e73e56e88ed008514a5bd120bb840a5846cd3d4a573bf0589',
    'mobilenet_v1_vww': '597a384c8c2c8a1276f04702f25013b7838f2f814f1ca7c174d295b73e3d6b7b',
    'ds_cnn_kws': 'aeea436800704fce17b17292e4412630ad856e9d777c044c64ef748a880bd0ae',
    'resnet8_cifar10': '3c002613d1b2475eb51dd78dfb85a546c8ae658dee71cf6ade43b022fe205415',
}

def validate_model(directory: Path) -> dict:
    manifest = json.loads((directory/'manifest.json').read_text())
    name = manifest['name']
    if name not in MODELS or manifest['model']['sha256'] != MODEL_SHA256[name]:
        raise ValueError('Unexpected model identity: ' + name)
    if manifest['rounding_mode'] != 'nearest_even' or not manifest['numerical_reference_complete']:
        raise ValueError('Complete nearest-even references are required')
    records = [manifest['model']]
    for sample in manifest['samples']:
        if len(sample['nodes']) != len(manifest['graph']['nodes']):
            raise ValueError('Missing operator output references')
        records += [sample['input'], sample['output'], *sample['nodes']]
    for record in records:
        path = (directory/record['path']).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError('Payload path leaves its model directory')
        raw = path.read_bytes()
        if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Payload hash or length differs: ' + str(path))
    return {'model': name, 'model_sha256': manifest['model']['sha256'],
            'samples': len(manifest['samples']), 'operators': len(manifest['graph']['nodes']),
            'verified_payloads': len(records), 'passed': True}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    root = args.prepared.resolve()
    reports = [validate_model(root/name) for name in MODELS]
    if args.out and args.out.resolve() != root:
        shutil.copytree(root, args.out.resolve(), dirs_exist_ok=False)
    print(json.dumps({'passed': True, 'models': reports}, indent=2))

if __name__ == '__main__':
    main()
