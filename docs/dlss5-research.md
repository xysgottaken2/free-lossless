# DLSS 5 Neural Rendering — Technical Research Notes

> Status: research completed before implementation (2026-09-30).
> Rule applied throughout: **no NVIDIA API was invented**. Everything below is
> either (a) taken from NVIDIA's public NGX documentation/headers, or (b) observed
> in real open-source implementations that run against `nvngx_dlssnr.dll`, with
> the source cited. Anything not confirmed is explicitly marked **UNKNOWN**.

---

## 1. What "DLSS 5 Neural Rendering" actually is

It is **not** DLSS Super Resolution and **not** DLSS-G/Multi Frame Generation.

| Technology | DLL | NGX feature id | Purpose | Official HW |
|---|---|---|---|---|
| DLSS Super Resolution / DLAA | `nvngx_dlss.dll` | 1 (`SuperSampling`) | temporal upscaling | RTX 20+ |
| DLSS Ray Reconstruction | `nvngx_dlssd.dll` | 13 (`RayReconstruction`) | denoising | RTX 20+ (as used) |
| DLSS Frame Generation (DLSS-G) | `nvngx_dlssg.dll` | 11 (`FrameGeneration`) | interpolation/extrapolation | RTX 40+ |
| DLSS Multi Frame Generation | `nvngx_dlssg.dll` | (FG variants) | 3x/4x FG | RTX 50 only |
| **DLSS 5 Neural Rendering (DLSSNR)** | **`nvngx_dlssnr.dll`** | **18 (`Reserved18`)** | **neural re-rendering / visual enhancement of an already-rendered image** | **RTX 50 (Blackwell) officially** |

Sources:
- Feature enum (incl. `NVSDK_NGX_Feature_Reserved18 = 18`): `nvsdk_ngx_defs.h` shipped in the
  public NVIDIA DLSS/NGX SDK headers (copy examined inside
  [DLSS5-NeuralScreen-Linux](https://github.com/malik05051/DLSS5-NeuralScreen-Linux) `native/include/`,
  MIT repo carrying NVIDIA headers for build purposes).
- Runtime discovery: NBA 2K27 early access ships `nvngx_dlssnr.dll` (NVIDIA DLSSNR 310.8.0.0,
  ~158 MB) — [TweakTown](https://www.tweaktown.com/news/113305/nvidias-dlss-5-neural-rendering-tech-has-been-found-in-the-first-publicly-accessible-game/index.html),
  [Guru3D](https://www.guru3d.com/story/first-dlss-5-runtime-discovered-in-nba-2k27-pc-build/),
  [VideoCardz](https://videocardz.com/newz/breaking-modders-unlock-experimental-nvidia-dlss-5-hours-after-dll-discovery).
- Community experiments (RenoDX/ReShade) reprocess the rendered image with a neural model
  (faces, skin, hair, materials, lighting) — [Igor's Lab DLSS 5 ReShade guide](https://www.igorslab.de/en/install-dlss-5-reshade-compatible-games/),
  [Wccftech](https://wccftech.com/nvidia-dlss-5-neural-rendering-in-10-modern-games-the-best-unofficial-dlss-5-on-vs-off-comparisons-so-far/).

Important performance note (Igor's Lab, VideoCardz/NeuralScreen): DLSSNR in this form is a
**quality** stage, not a performance stage. Even an RTX 5090 can lose ~half its FPS in-game;
NeuralScreen measures ~43 FPS for 4K desktop processing on an RTX 5070 Ti and caps its neural
work resolution at 2560×1440.

---

## 2. How real implementations drive the runtime

Three integration families exist in the wild:

1. **ReShade add-on / hook path** (RenoDX `renodx-dlss5.addon64`, DLSS5-Feeder, OptiScaler_DLSSNR
   forks, DLSS 5 Bridge, neural-upstream): hook a *game's* NVSDK_NGX_D3D12 calls (or synthesize a
   "DLAA contract" with color/depth/motion-vectors on a private D3D12 device) and run feature 18
   from the add-on. Requires ReShade inside the game process.
2. **Standalone worker path** (Wan2GP `nr-depth-worker`, Merserk `dlss5-visual-enhancer` "Neuroframe
   Engine", NeuralScreen, `nvngx.dll_nr.exe` in DLSS5-NeuralScreen-Linux, te_dlss5_native bridge for
   ComfyUI): an **external** process owns its own D3D12 device, loads `nvngx_dlssnr.dll` and runs
   feature 18 on its own textures. No game injection.
3. **Vendor reimplementation** (DLSS-NR-on-AMD): re-executes the model via HIP on AMD GPUs
   (closed source, RDNA3/4). Not applicable here.

**Free Lossless chooses family 2** — it matches the project's "no injection, external capture"
identity and the target overlay use case (the same shape as NeuralScreen and as the
"DLSS 5 into Lossless Scaling" community experiments, where the enhancer processes the
already-captured output rather than hooking the game).

### 2.1 The two documented blockers for direct calls (and their solutions)

Real projects measured these failure modes:

- **Module-name gate**: the snippet "refuses calls from a module whose path lacks the substring
  `nvngx.dll`" (documented in `nvngx.dll_nr.cpp` of
  [DLSS5-NeuralScreen-Linux](https://github.com/malik05051/DLSS5-NeuralScreen-Linux) and by
  [neural-upstream](https://github.com/matiasLombo/neural-upstream): *"The filename matters. The
  NGX snippet gates feature creation on the calling module's path containing nvngx.dll; under any
  other name it returns 0xBAD00002"*). Community bridges pass the check by naming themselves
  `deep-fried-chicken-nvngx.dll`, `nvngx.dll_nr.exe`, `nvngx.dll.addon64`, etc.
  → **Our bridge DLL is therefore named `freelossless-nvngx.dll`.**
- **NGX-core-driven init**: loading `nvngx_dlssnr.dll` alone and calling
  `NVSDK_NGX_D3D12_Init_Ext` directly fails: *"All the exports are present, but
  NVSDK_NGX_D3D12_Init_Ext rejects every combination of application id and API version with
  0xBAD00002 (FAIL_PlatformError)"* — [dlss5-webcam-demo](https://github.com/jpneagle/dlss5-webcam-demo)
  README ("Calling Feature 18 directly (blocked)"). Their log line *"The snippet expects to be
  driven by the NGX core (`_nvngx.dll`)"* and the working sequence in `nvngx.dll_nr.cpp` show the
  fix: **load the driver's NGX core first** (`_nvngx.dll`/`nvngx.dll`; on Windows installed under
  `C:\Program Files\NVIDIA Corporation\NVIDIA NGX\`), call the core's
  `NVSDK_NGX_D3D12_Init` + `NVSDK_NGX_D3D12_AllocateParameters`, and only then call the
  runtime's `NVSDK_NGX_D3D12_Init_Ext` and `CreateFeature`.

### 2.2 Confirmed call sequence (standalone worker, measured working)

From `nvngx.dll_nr.cpp` (MIT, DLSS5-NeuralScreen-Linux) and `DLSSNRBackend.cpp`
(MIT, dlss5-webcam-demo) — reimplemented independently in `native/src/flnr_bridge.cpp`:

1. `CreateDXGIFactory1` → `EnumAdapters1` until `VendorId == 0x10DE` → `D3D12CreateDevice`
   (feature level 12_0) + command queue/allocator/list/fence.
2. Load NGX core (`_nvngx.dll` / `nvngx.dll`):
   - `NVSDK_NGX_D3D12_Init(0x1000000, <writable log dir>, device, nullptr, NVSDK_NGX_Version_API)`
     (`NVSDK_NGX_VERSION_API_MACRO = 0x0000015`)
   - `NVSDK_NGX_D3D12_AllocateParameters(&params)`
3. Load `nvngx_dlssnr.dll`; resolve `NVSDK_NGX_D3D12_Init_Ext`, `..._CreateFeature`,
   `..._EvaluateFeature`, `..._ReleaseFeature`:
   - `NVSDK_NGX_D3D12_Init_Ext(0x1000000, dir, device, NVSDK_NGX_Version_API, params)`
4. `NVSDK_NGX_D3D12_CreateFeature(cmdList, 18 /* Reserved18 */, params, &handle)` with:
   - `CreationNodeMask=1`, `VisibilityNodeMask=1` (uint)
   - `DLSSNR.Width/Height` (neural work resolution)
   - `DLSSNR.InputWidth/InputHeight`, `DLSSNR.OutputWidth/OutputHeight`,
     `DLSSNR.Output.Width/Output.Height` (frame/io resolution)
   - `DLSSNR.Upscaling` (0/1), `DLSSNR.Scale`, `DLSSNR.ScalingRatio` (float, work/io)
   - `DLSSNR.Hint.Render.Preset` (uint; observed default `1` in working logs)
   - `DLSS.Feature.Create.Flags=0`
5. Per frame, `NVSDK_NGX_D3D12_EvaluateFeature(cmdList, handle, params, callback)` with:
   - `DLSSNR.Color` (R8G8B8A8_UNORM texture), `DLSSNR.Output` (UAV R8G8B8A8_UNORM),
     `DLSSNR.MVec` (R16G16_FLOAT UAV), optional `DLSSNR.Depth`
   - Subrect params (`DLSSNR.ColorSubrect*`, `DLSSNR.MVecSubrect*`, `DLSSNR.OutputSubrect*`)
   - `DLSSNR.MVecScaleX/Y=1.0`, `DLSSNR.DepthInverted=1` (when depth is used)
   - `DLSSNR.Enabled=1`, `DLSSNR.Reset` (0/1, temporal reset)
   - **User controls (confirmed real parameter names)**:
     `DLSSNR.Intensity` (float), `DLSSNR.Style` (uint; RenoDX reports **7 styles**),
     `DLSSNR.LocalToneStrength` (float), `DLSSNR.LocalStructureStrength` (float),
     `DLSSNR.SkinStructureStrength` (float), `DLSSNR.UseAutoMask` (uint)
   - `DLSS.Pre.Exposure=1.0`, `DLSS.Exposure.Scale` (float)
6. GPU-side copy of `Output` → readback buffer → CPU. Multi-pass ("MODE=TWO_PASSES" in the
   webcam demo log) re-evaluates with `Color` = previous pass output.
7. `NVSDK_NGX_D3D12_ReleaseFeature(handle)` on teardown; `NVSDK_NGX_D3D12_Shutdown` from core.

### 2.3 NVSDK_NGX_Parameter ABI

`NVSDK_NGX_Parameter` is an **MSVC C++ interface** with overloaded `Set()` methods. The worker
measured that *"the overloaded Set() methods sit in the vtable in the reverse of declaration
order"*, i.e. a non-MSVC-compiled caller must address the vtable by **MSVC index**:

| Method | MSVC vtable slot |
|---|---|
| `Set(const char*, ID3D12Resource*)` | 1 |
| `Set(const char*, unsigned int)` | 4 |
| `Set(const char*, float)` | 6 |
| clear/reset | 16 |

(These indices are ABI facts observed by the MIT-licensed worker, not an NVIDIA-published table.
Our bridge addresses the vtable by these indices, so the calling compiler does not matter.)

### 2.4 Result codes (public `nvsdk_ngx_defs.h`)

| Value | Meaning | Relevance |
|---|---|---|
| `0x00000001` | Success | |
| `0xBAD00001` | FAIL_FeatureNotSupported | architecture check: stock DLL on pre-Blackwell GPU |
| `0xBAD00002` | FAIL_PlatformError | (a) snippet called without NGX core / from a module name lacking `nvngx.dll`, or (b) driver rejects a signature-invalid (repacked/modified) `nvngx_dlssnr.dll` |
| `0xBAD00005` | FAIL_InvalidParameter | bad texture/param contract |
| `0xBAD0000B` | FAIL_UnableToInitializeFeature | |
| `0xBAD0000E` | FAIL_NotInitialized | |

`NVSDK_NGX_FAILED(value)` = `(value & 0xFFF00000) == 0xBAD00000`.

---

## 3. RTX 2060 / Turing (SM75) — separate investigation

Carefully separating the four technologies:

- **DLSS SR**: officially supported on RTX 20+. Not affected by any of this.
- **DLSS-G (Frame Generation)**: officially RTX 40+. A community SM75 mod (replacement kernels
  compiled for sm_75 + architecture-check spoofing, stock `nvngx_dlssg` 310.1) reportedly runs 2x
  FG on an RTX 2060 Max-Q
  ([VideoCardz](https://videocardz.com/newz/modder-gets-nvidia-dlss-frame-generation-running-on-geforce-rtx-20-gpus)).
  **We do not use DLSS-G at all — Free Lossless FG is RIFE.**
- **DLSS MFG**: RTX 50 only. Not used.
- **DLSS 5 Neural Rendering**:
  - **Official**: NVIDIA markets DLSS 5 NR for RTX 50 (Blackwell; FP8 5th-gen tensor cores /
    "Neural Flow Accelerator"). Official compatibility lists mark RTX 20 as unsupported.
  - **Community/measured reality**:
    - The leaked `nvngx_dlssnr.dll` 310.8.0.0 **contains CUDA kernels for multiple
      architectures**: the open-source [dlssnr-patcher](https://github.com/dev-camo/dlssnr-patcher)
      (GPL-2) extracts/decompiles the embedded CUDA fatbins and enables sm_75 (Turing), sm_86
      (Ampere), sm_89 (Ada) and sm_120 (Blackwell) paths; the NeuralScreen developer states the
      *"library contains kernels for Turing, Ampere, Ada and Blackwell GPUs, while NVIDIA's library
      blocks GPUs below Blackwell through an architecture check"*
      ([VideoCardz/NeuralScreen](https://videocardz.com/newz/dlss-5-is-escaping-games-modder-brings-neural-rendering-to-the-entire-windows-desktop)).
    - The stock DLL's architecture check fails with `0xBAD00001` on non-Blackwell; community
      builds (RenoDX Discord "SF"/"Lecram" builds, dlssnr-patcher output) lower the internal
      instruction precision (FP8→INT8/FP16) and enable older generations
      ([Nexus guide](https://www.nexusmods.com/cyberpunk2077/mods/33380), Wccftech, DLSS5-Feeder
      README).
    - Turing-specific evidence: DLSS5-Feeder reports a user-confirmed **RTX 2060** run (Star Wars
      KOTOR, OpenGL path) with a matching modified DLL; the user of this project has practical
      evidence of DLSS 5 NR working on an **RTX 2060 via Magpie + ReShade**; the Cyberpunk 2077
      guide documents RenoDX-community FP8→INT8/FP16 conversions "to make the neural model run on
      Ada Lovelace, Ampere, and Turing architectures".
  - **Conclusion for Free Lossless**: treat Turing support as **experimental**. The application
    does not patch or modify the runtime in any way. It loads whatever the user places in
    `native/`, runs the documented init sequence, verifies the result, and reports the raw NGX
    result code. A stock 310.8.0.0 DLL on an RTX 2060 is expected to fail with `0xBAD00001`;
    a community-patched build for Turing can work but is unsigned/modified (signature checks may
    fail with `0xBAD00002` — the same failure the installer of renodx-dlss-installer observed for
    a repacked DLL).

### 3.1 Known-good runtime file profile (for `native/README.txt`)

| File | Role | Required? | Where to get it |
|---|---|---|---|
| `nvngx_dlssnr.dll` | DLSS 5 Neural Rendering runtime (feature 18) | **Yes** | copied by the user from a licensed game that ships it (e.g. NBA 2K27 early access), or NVIDIA-authorized distribution. Community-modified builds for RTX 20/30/40 exist (unsigned) — user's own risk. |
| `nvngx.dll` (optional override) | NGX core | No (driver's copy is used) | installed by the NVIDIA driver at `C:\Program Files\NVIDIA Corporation\NVIDIA NGX\nvngx.dll` |
| `nvngx_dlss.dll` | DLSS SR runtime | **No** for our direct feature-18 path | some community setups place it alongside; the driver's copy may be found automatically |

We deliberately do **not** require ReShade, `renodx-dlss5.addon64`, `sl.interposer.dll` or
`nvngx_dlssg.dll`. Those belong to game-injection/DLSS-G paths.

**UNKNOWN / not implemented as UI controls** (they are RenoDX *compose* options, not confirmed
raw-runtime parameters): color strength, tone preservation, face/skin protection (beyond
`DLSSNR.SkinStructureStrength`), grain preservation, mask feather, shimmer suppression,
"local tone" naming variants. Confirmed raw-runtime controls are exactly the ones implemented:
Intensity, Style (0–6), LocalToneStrength, LocalStructureStrength, SkinStructureStrength,
UseAutoMask, preset (opaque uint), passes (multi-evaluate), processing scale (work vs io
resolution).

---

## 4. Sources used

| Project / article | License / status | What we took from it |
|---|---|---|
| [DLSS5-NeuralScreen-Linux](https://github.com/malik05051/DLSS5-NeuralScreen-Linux) (`nvngx.dll_nr.cpp`, `TECHNICAL.md`) | MIT | working standalone init sequence, module-name gate, `DLSSNR.*` param names, MSVC vtable slots |
| [dlss5-webcam-demo](https://github.com/jpneagle/dlss5-webcam-demo) (`DLSSNRBackend.cpp`) | MIT | second independent confirmation of the `DLSSNR.*` contract; the "Init_Ext without core = 0xBAD00002" blocker |
| [DLSS5-Feeder](https://github.com/jlrouzies-fr/DLSS5-Feeder) | MIT | architecture (private D3D12 + synthetic DLAA contract), Turing status table, runtime file expectations |
| [dlss5-visual-enhancer](https://github.com/Merserk/dlss5-visual-enhancer) | MIT | external-app "Neuroframe" precedent (image/video NR outside games) |
| [Wan2GP docs/DLSS5.md](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/DLSS5.md) | MIT (doc) | worker-process pattern, runtime layout & redistribution warnings |
| [OptiScaler_DLSSNR forks](https://github.com/Dagherbou/OptiScaler_DLSSNR) (Dagherbou/tB0nE/wilsjo2) | (check per-fork) | feature 18 dispatch via driver NGX core; `0xBAD00001`/`0xBAD00002` semantics |
| [dev-camo/dlssnr-patcher](https://github.com/dev-camo/dlssnr-patcher) | GPL-2 | evidence that the fatbins contain sm_75 (Turing) kernels and how the arch check is bypassed (we do not bundle or run it) |
| [neural-upstream](https://github.com/matiasLombo/neural-upstream) | (check) | "filename must contain nvngx.dll" gate |
| NVIDIA NGX/DLSS public docs & `nvsdk_ngx.h`/`nvsdk_ngx_defs.h` (via NVIDIA docs site / NVIDIA-DLSS GitHub) | NVIDIA public SDK docs | `NVSDK_NGX_D3D12_*` signatures, result codes, `NVSDK_NGX_Version_API` |
| VideoCardz / TweakTown / Guru3D / Wccftech / Igor's Lab / Nexus CP2077 guide / Reddit r/losslessscaling | press/community | runtime discovery, Turing modding status, RenoDX `DirectNeuralRendering*` config surface, Lossless Scaling+DLSS5 precedent |

No code was copied into this repository; `native/src/flnr_bridge.cpp` is an independent
implementation of the documented call sequence above. **No NVIDIA binary, header or model is
committed here, and none is downloaded by CI.**

---

## 5. Consequences for this project's design

1. `NeuralRenderer` abstraction (`neural/`) with `DisabledRenderer` + `DLSS5Renderer`; the
   pipeline never imports NVIDIA specifics.
2. Native bridge `native/freelossless-nvngx.dll` (built by our CI from `native/src/`, our own
   source) loads the **user-provided** `native/nvngx_dlssnr.dll` dynamically and verifies every
   init step, mapping known result codes to human-readable reasons.
3. Without the runtime the app runs `Capture → RIFE → Overlay` and logs
   `[DLSS5] Runtime not found / Neural Rendering disabled`.
4. Turing is documented as experimental; the app never patches the DLL and never claims
   compatibility. A failed `CreateFeature(18)` is a soft failure with fallback to RIFE.
5. Frame contract: SDR RGB8 frames in/out (display-referred, as the network expects), one GPU
   upload + one readback per processed frame; motion vectors are synthetic (zero-flow) since an
   external capture has no engine MVs — `DLSSNR.Reset` is therefore set per frame in the default
   (non-temporal) mode to avoid ghosting from stale accumulation.
