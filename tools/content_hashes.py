"""Small hash-manifest primitives shared by the edit guards."""
import hashlib
import json
from typing import NamedTuple

from filelock import FileLock


def digest(path):
    return digest_bytes(path.read_bytes())


def digest_bytes(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


class FileHashes(NamedTuple):
    digest: str
    compatible: set[str]


def file_hashes(path):
    data = path.read_bytes()
    normalized = data.replace(b"\r\n", b"\n")
    # Old manifests may contain the digest of the original bytes, including a CRLF checkout.
    canonical = hashlib.sha256(normalized).hexdigest()
    legacy = {hashlib.sha256(version).hexdigest()
              for version in {data, normalized.replace(b"\n", b"\r\n")} - {normalized}}
    return FileHashes(canonical, legacy | {canonical})


def matches(current, expected):
    return expected is None if current is None else expected in current.compatible


def load(path):
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("files"), dict):
        raise ValueError(f"invalid hash manifest: {path}")
    return data["files"]


def save(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"version": 1, "files": dict(sorted(files.items()))},
                                    indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def locked(path):
    """Serialize capture workers so recording one file cannot erase another worker's hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path) + ".lock", timeout=10)  # OS lock: released if the process dies


def differences(before, after):
    return {name: "added" if name not in before else "deleted" if name not in after else "changed"
            for name in sorted(before.keys() | after.keys()) if not matches(after.get(name), before.get(name))}
