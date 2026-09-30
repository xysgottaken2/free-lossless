Free Lossless - native/ folder (DLSS 5 Neural Rendering runtime)
================================================================

This folder holds EXTERNAL, OPTIONAL components that are NOT part of Free
Lossless and are NEVER downloaded or redistributed by this project.

The application works WITHOUT any of the DLLs below: with an empty native/
folder it simply runs the RIFE-only pipeline (Capture -> RIFE -> Overlay) and
reports:

    [DLSS5] Runtime not found
    [DLSS5] Neural Rendering disabled
    [RIFE] Frame Generation available


1. FILES
--------

native/
  freelossless-nvngx.dll   <- Free Lossless DLSS 5 bridge (OUR code, built by
                              this project's CI from native/src/, MIT-style).
                              Keep this file name: it must contain "nvngx.dll"
                              as a substring or the NVIDIA runtime refuses the
                              calls (error 0xBAD00002).
  README.txt               <- this file
  nvngx_dlssnr.dll         <- YOU provide this. NVIDIA DLSS 5 Neural Rendering
                              runtime ("NVIDIA DLSSNR", file version 310.8.0.0
                              is the widely tested one, ~158 MB).
  nvngx.dll                <- OPTIONAL override of the NVIDIA NGX core. By
                              default the driver's copy is used, installed at
                              C:\Program Files\NVIDIA Corporation\NVIDIA NGX\
                              nvngx.dll (comes with the NVIDIA display driver).

NOT required for Free Lossless (they belong to game-injection / DLSS-G paths):
  renodx-dlss5.addon64, ReShade (dxgi.dll), sl.interposer.dll, sl.common.dll,
  nvngx_dlssg.dll, nvngx_dlssd.dll.


2. WHERE TO GET nvngx_dlssnr.dll
-------------------------------

* The project does NOT distribute it (NVIDIA proprietary; redistribution is
  not permitted) and does NOT provide download links.
* The legitimate route: copy it out of a game you own that ships it (the file
  was first found in the NBA 2K27 early-access PC build), or obtain it from
  an NVIDIA-authorized distribution.
* Community-modified builds for pre-Blackwell GPUs (RTX 20/30/40) exist in
  community channels (e.g. the RenoDX Discord). They are UNSIGNED and MODIFIED;
  use them only if you accept the security/licensing risk and it is legal in
  your jurisdiction. Never download DLLs from random file-hosting sites.

3. COMPATIBILITY NOTES (see docs/dlss5-research.md for the full research)
------------------------------------------------------------------------

* Stock NVIDIA-signed builds create the neural feature on RTX 50 (Blackwell)
  only. On older GPUs the driver/architecture check fails with 0xBAD00001.
* RTX 20 (Turing, e.g. RTX 2060): EXPERIMENTAL. The runtime contains Turing
  kernels but NVIDIA blocks them behind the architecture check; community
  patches enable them. Free Lossless never patches the DLL - it loads whatever
  you provide and reports the exact NGX error code in the log/UI.
* The runtime may also refuse an unsigned/repacked DLL with 0xBAD00002.
* Without a working DLSS 5 runtime the application keeps running with RIFE.

4. PRIVACY
----------

Nothing in this folder is uploaded anywhere. The application only loads these
files locally; NVIDIA's runtime may write its own log files into native\logs\.
