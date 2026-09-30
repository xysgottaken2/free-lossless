# Free Lossless: Open AI Frame Generation + DLSS 5 Neural Rendering

![Logo]()

Free Lossless is a high-performance, **non-intrusive** frame generation and
visual enhancement tool for Windows. It works entirely from the **outside** of
the game or video: it captures the screen/window, optionally applies **NVIDIA
DLSS 5 Neural Rendering**, generates intermediate frames with **RIFE**, and
shows the result on a transparent, click-through overlay.

**No injection.** It never injects DLLs into the game, never hooks the game's
rendering pipeline, and never modifies game files.

```text
                    FREE LOSSLESS
                         │
                  Screen Capture
                  (DXCAM / BitBlt)
                         │
                         ▼
              ┌─────────────────────┐
              │ DLSS 5 Neural       │
              │ Rendering           │   OPTIONAL (external NVIDIA runtime)
              │ (visual enhance)    │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ RIFE Frame          │
              │ Generation          │   OPTIONAL (AI interpolation)
              │ (our FG engine)     │
              └──────────┬──────────┘
                         │
                         ▼
                  Transparent Overlay
```

Every stage can be toggled independently, so problems can be isolated:

```text
DLSS5 OFF + RIFE OFF      (capture -> overlay)
DLSS5 ON  + RIFE OFF      (capture -> neural enhance -> overlay)
DLSS5 OFF + RIFE ON       (capture -> RIFE -> overlay)        <- classic Free Lossless
DLSS5 ON  + RIFE ON       (capture -> neural -> RIFE -> overlay)
```

> **Important:** Frame Generation here is **RIFE**. DLSS-G / Multi Frame
> Generation are **not** used and are not planned as a replacement. DLSS 5 is
> used only for **Neural Rendering / visual enhancement**, as an optional stage.

---

## What is DLSS 5 Neural Rendering here?

DLSS 5 Neural Rendering ("DLSSNR", `nvngx_dlssnr.dll`, NGX feature 18) is a
neural post-process that re-renders an already-rendered image: skin, faces,
hair, materials, lighting. It is **not** DLSS Super Resolution and **not**
DLSS-G.

Free Lossless integrates it the way standalone tools do (NeuralScreen-style):
the app owns its own private D3D12 device and drives the NVIDIA runtime
directly through a small native bridge (`native/freelossless-nvngx.dll`, source
in `native/src/`, our own code). The full technical research, including the
exact NGX call sequence and which community implementations it was verified
against, lives in [`docs/dlss5-research.md`](docs/dlss5-research.md).

Because DLSSNR is expensive (it is a quality feature, not a performance
feature), the pipeline lets you lower its **processing scale** (neural work
resolution) independently of the output size.

---

## Requirements

* **Windows** 10/11 64-bit.
* **GPU**: any modern GPU for the RIFE pipeline (via **DirectML** — NVIDIA,
  AMD or Intel). An **NVIDIA RTX GPU** is required only for the optional DLSS 5
  stage.
* **Python** 3.10+ (or the standalone build from the GitHub Actions artifact).
* **RIFE**: the ONNX model is included (`models/rife_v4_lite.onnx`).
* **DLSS 5 Neural Rendering** (optional):
  * an NVIDIA GPU with a recent NVIDIA display driver (the driver provides the
    NGX core, `nvngx.dll`);
  * the **DLSSNR runtime** `nvngx_dlssnr.dll` — **external, user-supplied**
    (see below). The widely tested version is `310.8.0.0` (~158 MB).

### RTX 2060 / Turing status (read this)

Please keep the four NVIDIA technologies apart:

| Technology | What it is | Official HW | Used by Free Lossless? |
|---|---|---|---|
| DLSS Super Resolution | temporal upscaling | RTX 20+ | no |
| DLSS-G (Frame Generation) | interpolation | RTX 40+ | **no (we use RIFE)** |
| DLSS Multi Frame Generation | 3x/4x FG | RTX 50 only | no |
| **DLSS 5 Neural Rendering** | neural re-rendering | **RTX 50 officially** | **optional stage** |

* **Confirmed by NVIDIA**: DLSS 5 Neural Rendering targets RTX 50 (Blackwell).
* **Measured in the community** (research sources in
  [`docs/dlss5-research.md`](docs/dlss5-research.md)): the leaked/early
  `nvngx_dlssnr.dll` contains kernels for Turing (sm_75), Ampere, Ada and
  Blackwell; NVIDIA's architecture check blocks non-Blackwell GPUs (error
  `0xBAD00001`). Community-patched runtime builds enable RTX 20/30/40 and have
  been demonstrated on RTX 2060-class hardware (e.g. via Magpie + ReShade, and
  user reports with DLSS5-Feeder). The RenoDX community documents FP8→INT8/FP16
  model conversions for Ada/Ampere/**Turing**.
* **Our position**: Free Lossless treats RTX 20 / Turing as **EXPERIMENTAL**.
  The application **never patches** `nvngx_dlssnr.dll`; it loads whatever the
  user provides, verifies initialization (feature 18 creation + a probe frame)
  and reports the exact NGX error code. A stock DLL on an RTX 2060 is expected
  to fail the architecture check; a community Turing build may work — that is
  between you and the runtime you obtained.
* A passing GitHub Actions run **does not prove GPU compatibility** — the CI
  has no NVIDIA GPU and only exercises the software fallback paths.

---

## NVIDIA runtime (the `native/` folder)

The NVIDIA runtime is **proprietary**. This project:

* does **not** distribute it,
* does **not** download it (in the app or in CI),
* does **not** provide links to unofficial mirrors.

You place it manually:

```text
FreeLossless/
├── FreeLossless.exe
├── native/
│   ├── README.txt                  ← detailed instructions
│   ├── freelossless-nvngx.dll      ← our bridge (already in the ZIP)
│   └── nvngx_dlssnr.dll            ← YOU provide this (optional)
├── models/
├── config/
└── ...
```

Without `nvngx_dlssnr.dll` the application runs normally as
`Capture → RIFE → Overlay` and logs:

```text
[DLSS5] Runtime not found
[DLSS5] Neural Rendering disabled
[RIFE] Frame Generation available
```

### Which DLLs are actually needed?

| File | Needed? | Source |
|---|---|---|
| `nvngx_dlssnr.dll` | yes, for DLSS 5 | copy from a game you own that ships it (first seen in NBA 2K27 early access) or an NVIDIA-authorized distribution. Community-modified builds for RTX 20/30/40 exist but are unsigned/modified — use at your own risk |
| `nvngx.dll` (NGX core) | no | installed by the NVIDIA display driver (`C:\Program Files\NVIDIA Corporation\NVIDIA NGX\`); an override copy in `native/` takes precedence |
| ReShade, `renodx-dlss5.addon64`, `sl.interposer.dll`, `nvngx_dlssg.dll` | **no** | those belong to game-injection / DLSS-G setups, not to Free Lossless |

---

## Setup (from source)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Building the executable

```powershell
python build_app.py
```

The executable is generated in `dist/` (standalone, ~2.6 GB — it embeds Python,
PyTorch and the ONNX runtimes).

For the complete distributable ZIP (what the GitHub Actions `Build` workflow
produces), see the **FreeLossless-DLSS5** artifact of that workflow
(`workflow_dispatch` → run `Build`). ZIP layout:

```text
FreeLossless-DLSS5.zip
├── FreeLossless.exe
├── native/
│   ├── README.txt
│   └── freelossless-nvngx.dll
├── models/
├── config/
├── README.md
└── THIRD-PARTY.md
```

The ZIP never contains the NVIDIA runtime: download the ZIP, extract it, add
`native/nvngx_dlssnr.dll` yourself if you want DLSS 5, and run
`FreeLossless.exe`.

---

## Using DLSS 5 in the app

1. Make sure `native/nvngx_dlssnr.dll` exists (see above).
2. In the selection window, section **DLSS 5 Neural Rendering**:
   * `[ ] Enable DLSS 5 Neural Rendering`
   * status block: `Runtime: ... / GPU: ... / Backend: ... / Status: ...`
   * **Intensity** (0–1; community guidance 0.20–0.35), **Style** (0–6),
     **Passes** (1–2), **Processing scale** (1.0/0.75/0.5), **Automatic mask**
3. Frame generation (RIFE) is toggled independently with
   `[ ] Generación de Frames` + the engine selector.

All settings persist in `config/freelossless.json`.

The exposed controls map 1:1 to confirmed runtime parameters
(`DLSSNR.Intensity`, `DLSSNR.Style`, `DLSSNR.LocalToneStrength`,
`DLSSNR.LocalStructureStrength`, `DLSSNR.SkinStructureStrength`,
`DLSSNR.UseAutoMask`, `DLSSNR.Hint.Render.Preset`, multi-pass evaluation,
work-vs-io resolution). Sliders that are *not* confirmed in the real runtime
contract were deliberately **not** invented.

### Logs

```text
[DLSS5] Initializing...
[DLSS5] Runtime: nvngx_dlssnr.dll (310.8.0.0)
[DLSS5] GPU: NVIDIA GeForce RTX 2060
[DLSS5] Driver: ...
[DLSS5] Backend: ngx-core+dlssnr
[DLSS5] Input: 1280x720 RGB8
[DLSS5] Output: 1280x720 RGB8
[DLSS5] Model: nvngx_dlssnr.dll (310.8.0.0)
[DLSS5] Preset: 1
[DLSS5] Passes: 1
[DLSS5] Initialized successfully (812 ms)
```

On failure the app logs the reason, **disables DLSS 5 only**, and keeps the
RIFE pipeline running (`[DLSS5] Falling back to RIFE-only pipeline`).

### Error codes you may see

| Code | Meaning |
|---|---|
| `0xBAD00001` | FeatureNotSupported — architecture check (stock runtime on a pre-Blackwell GPU) |
| `0xBAD00002` | PlatformError — runtime not driven through the NGX core / module-name gate, **or** the driver rejected an unsigned/modified runtime build |
| `0xBAD0000E` | NotInitialized |

---

## Testing

```powershell
pip install numpy pytest opencv-python-headless
python -m pytest tests/ -v
```

The suite covers: the pipeline stage combinations (all four), config
save/load, the no-runtime fallback, an invalid-runtime fallback, mid-run
neural failure fallback, and UI status text. It runs on machines **without**
any GPU — which also means it cannot prove DLSS 5 behavior on real hardware.

---

## Licensing

See [`THIRD-PARTY.md`](THIRD-PARTY.md). In short: no NVIDIA binaries, models
or headers are committed or distributed by this project; the NVIDIA runtime
you provide remains NVIDIA's property and is subject to its own license.
