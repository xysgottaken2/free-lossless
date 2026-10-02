"""Execution providers shared by the ONNX engines (RIFE and the AI upscaler).

Order matters: DirectML works on every Windows GPU (NVIDIA, AMD and Intel), then
CUDA when the runtime ships it, and the CPU last. An engine that quietly runs on
the CPU looks like a broken filter — it is hundreds of times slower — so both the
selection and the description of the chosen provider are logged.
"""
import diagnostics

PREFERRED = ("DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider")
GPU_PROVIDERS = ("DmlExecutionProvider", "CUDAExecutionProvider")


def provider_names():
    """Providers of the installed onnxruntime build, best first."""
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - onnxruntime ships with the app
        diagnostics.write_now("onnx", f"onnxruntime indisponível: {exc}")
        return []
    try:
        available = set(ort.get_available_providers())
    except Exception as exc:  # pragma: no cover - defensive
        diagnostics.write_now("onnx", f"não foi possível listar os provedores: {exc}")
        return ["CPUExecutionProvider"]
    chosen = [name for name in PREFERRED if name in available]
    return chosen or ["CPUExecutionProvider"]


def describe(session):
    """Human readable provider list of a session, for the log."""
    try:
        return " · ".join(session.get_providers())
    except Exception:
        return "?"


def is_gpu(providers):
    """True when one of the providers runs on a GPU."""
    if isinstance(providers, str):
        providers = [providers]
    return any(name in GPU_PROVIDERS for name in providers or [])


def create_session(model_path, options=None):
    """Create an inference session, preferring the GPU providers."""
    import onnxruntime as ort

    providers = provider_names()
    return ort.InferenceSession(model_path, sess_options=options, providers=providers), providers
