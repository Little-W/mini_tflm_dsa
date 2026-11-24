#!/usr/bin/env python3
"""Read exact reference files from Git or a verified source archive."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


ARCHIVE_ENV = "NPU_RTL_REFERENCE_ROOT"
DEFAULT_ARCHIVE = Path(__file__).resolve().with_suffix("") / "data"


class ReferenceUnavailable(RuntimeError):
    """The requested revision or file has not been supplied."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def relative_name(path: str | Path) -> str:
    value = str(path)
    pure = PurePosixPath(value)
    if not value or "\\" in value or "\0" in value or pure.is_absolute() or \
            ".." in pure.parts or pure.as_posix() != value or value == ".":
        raise ValueError("Reference path must be a normalized repository-relative path")
    return value


def resolve_git(root: Path, reference: str) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                             "--end-of-options", reference + "^{commit}"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        return None
    revision = result.stdout.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Reference source archives require SHA-1 Git object identifiers")
    return revision


def read_git(root: Path, revision: str, relative: str) -> tuple[bytes, str, str]:
    result = subprocess.run(["git", "-C", str(root), "ls-tree", "-z", revision, "--", relative],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    matches = [entry for entry in result.stdout.split(b"\0")
               if entry and entry.split(b"\t", 1)[1].decode() == relative]
    if not matches:
        raise FileNotFoundError(f"Reference file does not exist: {revision}:{relative}")
    mode, kind, blob = matches[0].split(b"\t", 1)[0].decode().split()
    if kind != "blob" or mode not in ("100644", "100755"):
        raise ValueError("Reference input must be a regular source file: " + relative)
    content = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", blob])
    if git_blob(content) != blob:
        raise ValueError("Reference Git blob digest differs: " + relative)
    return content, blob, mode


def read_manifest(archive: Path) -> dict:
    path = archive / "manifest.json"
    if not path.is_file():
        raise ReferenceUnavailable("Reference source manifest is unavailable: " + str(path))
    value = json.loads(path.read_text())
    if value.get("format_version") != 1 or value.get("git_object_format") != "sha1":
        raise ValueError("Unsupported reference source archive format")
    if not all(re.fullmatch(r"[0-9a-f]{40}", key) for key in value["references"]):
        raise ValueError("Archive revisions must contain complete Git commit identifiers")
    return value


def resolve_archive(manifest: dict, reference: str) -> str:
    aliases = manifest.get("aliases", {})
    if reference in aliases:
        revision = aliases[reference]
        if revision not in manifest["references"]:
            raise ValueError("Reference alias names an unavailable revision")
        return revision
    if not re.fullmatch(r"[0-9a-f]{7,40}", reference):
        raise ReferenceUnavailable("Reference revision is not archived: " + reference)
    matches = [revision for revision in manifest["references"] if revision.startswith(reference)]
    if len(matches) != 1:
        raise ReferenceUnavailable("Reference revision is missing or ambiguous: " + reference)
    return matches[0]


def read_archived(archive: Path, manifest: dict, revision: str, relative: str) -> bytes:
    files = manifest["references"][revision]["files"]
    if relative not in files:
        raise ReferenceUnavailable(f"File is not included in the source archive: {revision}:{relative}")
    entry = files[relative]
    if entry.get("exists") is False:
        raise FileNotFoundError(f"Reference file does not exist: {revision}:{relative}")
    checksum = entry["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Invalid reference source digest")
    description = manifest["objects"][checksum]
    if description["bytes"] != entry["bytes"]:
        raise ValueError("Reference source lengths differ: " + relative)
    object_path = archive / "objects" / (checksum + ".gz")
    if not object_path.resolve().is_relative_to(archive.resolve()):
        raise ValueError("Reference object path leaves the archive")
    compressed = object_path.read_bytes()
    if len(compressed) != description["compressed_bytes"] or \
            sha256(compressed) != description["compressed_sha256"]:
        raise ValueError("Compressed reference object digest differs: " + relative)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
        content = source.read(entry["bytes"] + 1)
    if len(content) != entry["bytes"] or sha256(content) != checksum or \
            git_blob(content) != entry["git_blob"]:
        raise ValueError("Reference source content differs: " + relative)
    return content


def resolve_reference(root: str | Path, reference: str, *, archive_root: str | Path | None = None) -> str:
    """Return the complete original commit identifier for a Git or archived input."""
    revision = resolve_git(Path(root).resolve(), str(reference))
    if revision is not None:
        return revision
    archive = Path(archive_root or os.environ.get(ARCHIVE_ENV) or DEFAULT_ARCHIVE).resolve()
    return resolve_archive(read_manifest(archive), str(reference))


def read_reference_file(root: str | Path, reference: str, path: str | Path, *,
                        archive_root: str | Path | None = None, text: bool = False):
    """Return original bytes, with verified archived files available after history compaction."""
    root, relative = Path(root).resolve(), relative_name(path)
    revision = resolve_git(root, str(reference))
    if revision is not None:
        content, _, _ = read_git(root, revision, relative)
    else:
        selected = archive_root or os.environ.get(ARCHIVE_ENV) or DEFAULT_ARCHIVE
        archive = Path(selected).resolve()
        manifest = read_manifest(archive)
        revision = resolve_archive(manifest, str(reference))
        content = read_archived(archive, manifest, revision, relative)
    return content.decode("utf-8") if text else content


def export_archive(root: str | Path, requests: dict, output: str | Path) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Reference archive output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "objects").mkdir()
    manifest = {"format_version": 1, "git_object_format": "sha1", "references": {},
                "aliases": {}, "objects": {}}
    for reference, paths in sorted(requests["references"].items()):
        revision = resolve_git(root, reference)
        if revision is None:
            raise ReferenceUnavailable("Cannot export unavailable Git revision: " + reference)
        manifest["aliases"][reference] = revision
        files = manifest["references"].setdefault(revision, {"files": {}})["files"]
        for path in sorted(set(paths)):
            relative = relative_name(path)
            try:
                content, blob, mode = read_git(root, revision, relative)
            except FileNotFoundError:
                files[relative] = {"exists": False}
                continue
            checksum = sha256(content)
            files[relative] = {"exists": True, "sha256": checksum, "git_blob": blob,
                               "git_mode": mode, "bytes": len(content)}
            if checksum not in manifest["objects"]:
                compressed = gzip.compress(content, compresslevel=9, mtime=0)
                (output / "objects" / (checksum + ".gz")).write_bytes(compressed)
                manifest["objects"][checksum] = {"bytes": len(content),
                    "compressed_bytes": len(compressed), "compressed_sha256": sha256(compressed)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return verify_archive(output)


def verify_archive(archive: str | Path) -> dict:
    archive = Path(archive).resolve()
    manifest = read_manifest(archive)
    present = absent = 0
    for alias, expected in manifest["aliases"].items():
        if resolve_archive(manifest, alias) != expected:
            raise ValueError("Reference alias differs: " + alias)
    for revision, row in manifest["references"].items():
        for path, entry in row["files"].items():
            relative_name(path)
            if entry.get("exists") is False:
                absent += 1
            else:
                read_archived(archive, manifest, revision, path)
                present += 1
    referenced = {entry["sha256"] for row in manifest["references"].values()
                  for entry in row["files"].values() if entry.get("exists") is not False}
    if referenced != set(manifest["objects"]):
        raise ValueError("Reference object inventory differs from the file inventory")
    return {"passed": True, "references": len(manifest["references"]),
            "present_files": present, "absent_files": absent, "unique_objects": len(manifest["objects"]),
            "compressed_object_bytes": sum(row["compressed_bytes"] for row in manifest["objects"].values()),
            "manifest_sha256": sha256((archive / "manifest.json").read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export")
    export.add_argument("--repo", type=Path, required=True)
    export.add_argument("--requests", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    verify = actions.add_parser("verify")
    verify.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args()
    result = (export_archive(args.repo, json.loads(args.requests.read_text()), args.out)
              if args.action == "export" else verify_archive(args.archive_root))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
