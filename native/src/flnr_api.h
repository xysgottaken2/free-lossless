/*
 * flnr_api.h - C ABI of the Free Lossless DLSS 5 Neural Rendering bridge.
 *
 * This bridge is original code of the Free Lossless project.  It contains no
 * NVIDIA source, header or binary.  It dynamically loads two external,
 * user-supplied / driver-supplied components at run time:
 *
 *   1. the NVIDIA NGX core      (nvngx.dll - installed by the NVIDIA driver)
 *   2. the DLSSNR runtime       (nvngx_dlssnr.dll - supplied by the user in
 *                                 native/; NEVER redistributed by this project)
 *
 * and drives NGX feature 18 ("Reserved18", DLSS 5 Neural Rendering) on a
 * private D3D12 device.  The exact call sequence and parameter names are
 * documented in docs/dlss5-research.md (they were reverse-engineered from
 * measured-working open-source implementations, not invented).
 *
 * NOTE: the produced DLL must keep "nvngx.dll" as a substring of its file
 * name (we ship it as freelossless-nvngx.dll).  The DLSSNR runtime refuses
 * calls from modules whose path does not contain that substring (0xBAD00002).
 */
#ifndef FLNR_API_H
#define FLNR_API_H

#include <stdint.h>

#if defined(_WIN32)
#  if defined(FLNR_EXPORTS)
#    define FLNR_API __declspec(dllexport)
#  else
#    define FLNR_API __declspec(dllimport)
#  endif
#  define FLNR_CALL __cdecl
#else
#  define FLNR_API
#  define FLNR_CALL
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---- error codes ------------------------------------------------------- */
#define FLNR_OK                  0
#define FLNR_ERR_GENERIC        -1
#define FLNR_ERR_NO_D3D12       -2
#define FLNR_ERR_NO_NVIDIA_GPU  -3
#define FLNR_ERR_CORE_LOAD      -4
#define FLNR_ERR_CORE_INIT      -5
#define FLNR_ERR_RUNTIME_LOAD   -6
#define FLNR_ERR_RUNTIME_INIT   -7
#define FLNR_ERR_FEATURE        -8
#define FLNR_ERR_BAD_ARG        -9
#define FLNR_ERR_GPU            -10

/* ---- options ----------------------------------------------------------- */
typedef struct FlNrOptions {
    int32_t  width, height;           /* frame (io) size, RGB8 in/out        */
    int32_t  work_width, work_height; /* neural work resolution              */
    uint32_t passes;                  /* 1 = single evaluate, 2 = two passes */
    uint32_t preset;                  /* DLSSNR.Hint.Render.Preset (opaque)  */
    uint32_t style;                   /* DLSSNR.Style            (0..6 obs.) */
    float    intensity;               /* DLSSNR.Intensity        (0..1)      */
    float    local_tone;              /* DLSSNR.LocalToneStrength            */
    float    local_structure;         /* DLSSNR.LocalStructureStrength       */
    float    skin_structure;          /* DLSSNR.SkinStructureStrength        */
    float    exposure;                /* DLSS.Exposure.Scale                 */
    uint32_t auto_mask;               /* DLSSNR.UseAutoMask (0/1)            */
    uint32_t temporal;                /* 0 = DLSSNR.Reset every frame        */
} FlNrOptions;

/* ---- status ------------------------------------------------------------ */
typedef struct FlNrStatus {
    int32_t  initialized;
    int32_t  last_error;              /* FLNR_* code of last failure         */
    uint32_t last_ngx_result;         /* raw NVSDK_NGX_Result of last call   */
    uint64_t frames_ok;
    uint64_t frames_failed;
    uint32_t passes_active;
    int32_t  width, height;
    int32_t  work_width, work_height;
    wchar_t  gpu[128];
    wchar_t  runtime_version[64];
    wchar_t  core_path[260];
    wchar_t  runtime_path[260];
    char     backend[32];
} FlNrStatus;

/*
 * Probe the system and create the NGX feature.  Fails soft: returns a FLNR_*
 * code and writes a human-readable message into errbuf.  native_dir must
 * contain nvngx_dlssnr.dll (and may contain an nvngx.dll override); log_dir
 * must be writable (the NGX runtime writes logs there).
 */
FLNR_API int32_t FLNR_CALL flnr_init(const FlNrOptions* options,
                                     const wchar_t* native_dir,
                                     const wchar_t* log_dir,
                                     FlNrStatus* out_status,
                                     char* errbuf, int32_t errlen);

/*
 * Process one tightly-packed RGB8 frame.  in_stride/out_stride are in bytes
 * (>= width*3).  On success the output buffer holds the enhanced frame.
 */
FLNR_API int32_t FLNR_CALL flnr_process(const uint8_t* rgb_in, int32_t in_stride,
                                        uint8_t* rgb_out, int32_t out_stride,
                                        FlNrStatus* out_status,
                                        char* errbuf, int32_t errlen);

/* Copy the current status (thread-safe). */
FLNR_API int32_t FLNR_CALL flnr_get_status(FlNrStatus* out_status);

/* Release everything. Safe to call multiple times. */
FLNR_API void FLNR_CALL flnr_shutdown(void);

#ifdef __cplusplus
}
#endif

#endif /* FLNR_API_H */
