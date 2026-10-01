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

def build():
    print(f"Building {exe_name}...")
    
    # Ensure build directories are clean
    if os.path.exists("dist"):
        shutil.rmtree("dist")
    if os.path.exists("build"):
        shutil.rmtree("build")

    params = [
        script_name,
        "--name", exe_name,
        "--onefile",
        "--noconsole", # GUI mode
        "--clean",
    ]

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
    
    print("\nBuild Complete! Executable is in the 'dist' folder.")

if __name__ == "__main__":
    build()
