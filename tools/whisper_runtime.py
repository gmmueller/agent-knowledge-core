"""Shared faster-whisper device selection; Apple GPUs use the CPU backend."""
import os
from pathlib import Path
import sys

_dll_handles = []


def load_cuda_dlls() -> None:
    if sys.platform != "win32" or _dll_handles:
        return
    try:
        import nvidia
    except ImportError:
        return  # A system CUDA installation can supply the libraries instead.
    for base in nvidia.__path__:
        for folder in Path(base).glob("*/bin"):
            _dll_handles.append(os.add_dll_directory(str(folder)))
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")


def model_options() -> dict:
    load_cuda_dlls()
    import ctranslate2

    try:
        cuda = ctranslate2.get_cuda_device_count() > 0
    except RuntimeError:
        cuda = False
    return {"device": "cuda" if cuda else "cpu", "compute_type": "float16" if cuda else "int8"}
