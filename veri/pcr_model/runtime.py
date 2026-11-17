"""Python interface to the shared GEMM RTL backend."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("shared_gemm_runtime", ROOT / "veri/python_model/runtime.py")
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

NpuModel = _shared.NpuModel
SCALARS = _shared.SCALARS
LANES = _shared.LANES
config_words = _shared.config_words
read_words = _shared.read_words
sha256 = _shared.sha256


def available_backends():
    roots = [ROOT / "build/pcr_model/backends", Path(__file__).resolve().parent / "backends"]
    return sorted({*(_shared.available_backends()),
                   *(p.parent for root in roots for p in root.glob("*/manifest.json")
                     if (p.parent / "rtl_server").is_file())})
