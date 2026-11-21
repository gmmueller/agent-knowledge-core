"""Small hash-manifest primitives shared by the edit guards."""
import hashlib
import json

from filelock import SoftFileLock


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return SoftFileLock(str(path) + ".lock", timeout=10)


def differences(before, after):
    return {name: "added" if name not in before else "deleted" if name not in after else "changed"
            for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)}
