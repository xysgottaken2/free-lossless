# Third-party components and licensing notes

## Policy for the DLSS 5 integration (read first)

* **No NVIDIA proprietary binary, model or SDK header is committed to this
  repository, built into the executable, downloaded by CI, or included in any
  release artifact.**
* The optional `native/nvngx_dlssnr.dll` (and any `nvngx.dll` override) are
  provided by the user, remain NVIDIA's property, and are governed by NVIDIA's
  own license terms. The user is responsible for complying with them.
* The native bridge `native/freelossless-nvngx.dll` is **original code** of
  this project, built from `native/src/`. It implements the publicly documented
  NVSDK_NGX function signatures and a call sequence verified against
  open-source implementations (cited in `docs/dlss5-research.md`). No code was
  copied from those projects.
* The GitHub Actions `Build` workflow contains an explicit guard that fails if
  any NVIDIA runtime DLL would end up in the distribution ZIP.

## Upstream project

* **Free Lossless** (this repository's base): the upstream project
  (`metantonio/free-lossless`) does not currently ship a LICENSE file. All
  original code remains under the upstream author's terms; additions in this
  branch are provided under the same terms as the project as a whole.

## Bundled models (`models/`)

| File | Notes |
|---|---|
| `rife_v4_lite.onnx` | ONNX conversion of the RIFE frame-interpolation model. Provenance inherited from the upstream Free Lossless project. The RIFE reference implementation and weights are distributed by the RIFE authors under their own terms — **verify redistribution rights before shipping commercial builds**. |
| `fsrcnn_x2.onnx` | FSRCNN x2 super-resolution model, provenance inherited from the upstream project. |

## Python dependencies (`requirements.txt`)

| Package | License (typical) | Notes |
|---|---|---|
| `dxcam` | MIT | screen capture |
| `torch`, `torchvision` | BSD-3-Clause-style (PyTorch) | bundled into the standalone exe |
| `opencv-python` | Apache-2.0 | image processing |
| `numpy` | BSD-3-Clause | |
| `pygame` | LGPL-2.1-or-later (+ linking exception) | overlay window |
| `psutil` | BSD-3-Clause | process priority |
| `pywin32` | PSF-based | Win32 bindings |
| `onnxruntime-directml` | MIT | RIFE/ONNX inference (DirectML) |
| `requests` | Apache-2.0 | |
| `pyinstaller` | GPL-2.0-with-Bootloader-exception | **build-time only**; the produced executables are not subject to the GPL via the bootloader exception. If you distribute a modified `PyInstaller` itself, the GPL applies. |

License names above reflect the standard upstream licenses of these projects;
always re-verify against the exact versions you install.

## Research references (documentation only — nothing bundled)

See `docs/dlss5-research.md` for the full list (DLSS5-NeuralScreen-Linux,
dlss5-webcam-demo, DLSS5-Feeder, dlss5-visual-enhancer, Wan2GP,
OptiScaler_DLSSNR forks, dlssnr-patcher, neural-upstream, NVIDIA NGX public
documentation). Those projects were used to *understand* the NVIDIA runtime
contract; none of their code or binaries are redistributed here.

`dlssnr-patcher` (GPL-2) is **not** used, bundled or executed by this project.
