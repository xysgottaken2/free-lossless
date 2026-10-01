import PyInstaller.__main__
import os
import shutil

# --- Configuration ---
script_name = "main.py"
exe_name = "FreeLossless"
icon_path = None # Add icon path here if available

# Data folders to include
# Format: (Source, Destination)
datas = [
    ("models", "models"),
]

def check_gpu_runtime():
    """Warn early when the ONNX runtime has no GPU provider.

    PyInstaller's onnxruntime hook collects the provider DLLs (including
    DirectML.dll), but only from the package that is installed. A CPU-only
    onnxruntime makes every AI filter fall back to the CPU, which is hundreds of
    times slower, so the build should say it out loud.
    """
    try:
        import onnxruntime
    except ImportError:
        print("WARNING: onnxruntime is not installed; the AI filters will be disabled.")
        return
    providers = onnxruntime.get_available_providers()
    print(f"onnxruntime providers: {providers}")
    if not any(name in providers for name in ("DmlExecutionProvider", "CUDAExecutionProvider")):
        print("WARNING: no GPU provider found. Install 'onnxruntime-directml' before building,")
        print("         otherwise the AI engines run on the CPU.")


# Hidden imports that might be missed
hidden_imports = [
    "onnxruntime",
    "cv2",
    "pygame",
    "multiprocessing",
    "win32gui",
    "win32ui",
    "win32process",
    "dxcam.processor.numpy_processor",
    "win32con",
    "win32api",
    "psutil",
    "requests",
]

def build(mode="onefile"):
    """Build the app.

    ``onefile`` gives a single .exe that unpacks itself on every start (slow on a
    ~260 MB bundle). ``onedir`` gives a folder with the executable next to its
    DLLs, which opens in a fraction of the time. Both are built for the releases;
    the folder version is the one to use day to day.
    """
    if mode == "both":
        build("onefile")
        build("onedir")
        return
    print(f"Building {exe_name} ({mode})...")

    # Ensure build directories are clean
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")

    params = [
        script_name,
        "--name", exe_name,
        "--noconsole", # GUI mode
        "--clean",
    ]
    if mode == "onefile":
        params.append("--onefile")

    # Add datas
    for src, dst in datas:
        if os.path.exists(src):
            params.extend(["--add-data", f"{src}{os.pathsep}{dst}"])

    # Add hidden imports
    for imp in hidden_imports:
        params.extend(["--hidden-import", imp])

    check_gpu_runtime()

    # Run PyInstaller
    PyInstaller.__main__.run(params)

    print(f"\nBuild Complete! ({mode})")
    if mode == "onedir":
        print("Portable folder: dist/FreeLossless/FreeLossless.exe (open this one for faster start)")
    else:
        print("Single file: dist/FreeLossless.exe")


if __name__ == "__main__":
    import sys

    requested = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else "onefile"
    if requested not in ("onefile", "onedir", "both"):
        raise SystemExit("usage: python build_app.py [onefile|onedir|both]")
    build(requested)
