/*
 * flnr_bridge.cpp - Free Lossless DLSS 5 Neural Rendering bridge (D3D12).
 *
 * Original implementation (see flnr_api.h for the policy notes).  What it
 * does, in order:
 *
 *   1. Creates a private D3D12 device on the NVIDIA adapter.
 *   2. Loads the driver's NGX core (nvngx.dll) and initializes it
 *      (NVSDK_NGX_D3D12_Init + AllocateParameters).
 *   3. Loads the user-supplied nvngx_dlssnr.dll and initializes the snippet
 *      (NVSDK_NGX_D3D12_Init_Ext) - this order matters: calling the snippet
 *      without the core fails with 0xBAD00002 (measured, see the research
 *      doc in docs/dlss5-research.md).
 *   4. Creates NGX feature 18 ("Reserved18" = DLSS 5 Neural Rendering) with
 *      the DLSSNR.* parameters used by measured-working standalone tools.
 *   5. Evaluates it per frame on our own textures and reads the result back.
 *
 * The NVSDK_NGX_Parameter interface is an MSVC C++ interface whose overloaded
 * Set() methods must be addressed by their MSVC vtable slot (1 = resource,
 * 4 = unsigned int, 6 = float, 16 = clear); we therefore call through raw
 * vtable slots so the compiler used to build this DLL does not matter.
 *
 * Failure policy: every entry point returns a FLNR_* code with a message;
 * nothing throws; the host process keeps running if the runtime misbehaves.
 */

#define WIN32_LEAN_AND_MEAN
#define INITGUID
#define FLNR_EXPORTS
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <cstdio>
#include <cstdarg>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>

#include "flnr_api.h"

/* ------------------------------------------------------------------------- */
/* Minimal NGX surface (function signatures are the public NVIDIA NGX API).   */
/* ------------------------------------------------------------------------- */

#define FLNR_NGX_VERSION_API 0x0000015u /* NVSDK_NGX_VERSION_API_MACRO 1.5.0 */
#define FLNR_NGX_SUCCESS     0x1u
#define FLNR_NGX_FAILED(v)   ((((uint32_t)(v)) & 0xFFF00000u) == 0xBAD00000u)
#define FLNR_FEATURE_DLSSNR  18         /* NVSDK_NGX_Feature_Reserved18     */

struct NVSDK_NGX_Parameter;             /* opaque; accessed via vtable slots */
struct NVSDK_NGX_Handle;                /* opaque feature handle            */
struct NVSDK_NGX_FeatureCommonInfo;     /* opaque; we always pass nullptr   */

typedef uint32_t NVSDK_NGX_Result;

typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_INIT)(
    unsigned long long, const wchar_t*, ID3D12Device*,
    const NVSDK_NGX_FeatureCommonInfo*, unsigned int);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_ALLOC_PARAMS)(NVSDK_NGX_Parameter**);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_INIT_EXT)(
    unsigned long long, const wchar_t*, ID3D12Device*, unsigned int,
    const NVSDK_NGX_Parameter*);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_CREATE)(
    ID3D12GraphicsCommandList*, int, const NVSDK_NGX_Parameter*, NVSDK_NGX_Handle**);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_EVAL)(
    ID3D12GraphicsCommandList*, const NVSDK_NGX_Handle*,
    const NVSDK_NGX_Parameter*, void*);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_RELEASE)(NVSDK_NGX_Handle*);
typedef NVSDK_NGX_Result (FLNR_CALL *PFN_NGX_SHUTDOWN12)();

/* MSVC vtable slots of NVSDK_NGX_Parameter (see research doc section 2.3). */
enum {
    SLOT_SET_RESOURCE = 1,
    SLOT_SET_UINT     = 4,
    SLOT_SET_FLOAT    = 6,
    SLOT_CLEAR        = 16
};

struct NgxParams {
    NVSDK_NGX_Parameter* obj;

    NgxParams() : obj(nullptr) {}

    template <typename F> F slot(int index) const {
        void** vtable = *reinterpret_cast<void***>(obj);
        return reinterpret_cast<F>(vtable[index]);
    }
    void set_resource(const char* name, ID3D12Resource* value) {
        slot<void (FLNR_CALL*)(void*, const char*, ID3D12Resource*)>(SLOT_SET_RESOURCE)(obj, name, value);
    }
    void set_uint(const char* name, unsigned int value) {
        slot<void (FLNR_CALL*)(void*, const char*, unsigned int)>(SLOT_SET_UINT)(obj, name, value);
    }
    void set_float(const char* name, float value) {
        slot<void (FLNR_CALL*)(void*, const char*, float)>(SLOT_SET_FLOAT)(obj, name, value);
    }
    void clear() {
        if (obj) slot<void (FLNR_CALL*)(void*)>(SLOT_CLEAR)(obj);
    }
};

/* ------------------------------------------------------------------------- */
/* Small helpers                                                              */
/* ------------------------------------------------------------------------- */

namespace {

CRITICAL_SECTION g_lock;
bool g_lock_ready = false;

void set_err(char* buf, int32_t len, const char* fmt, ...) {
    if (!buf || len <= 0) return;
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, (size_t)len, fmt, args);
    va_end(args);
    buf[len - 1] = '\0';
}

template <typename T> void release_com(T*& p) {
    if (p) { p->Release(); p = nullptr; }
}

uint32_t align256(uint32_t bytes) { return (bytes + 255u) & ~255u; }

void wcopy(wchar_t* dst, size_t cap, const wchar_t* src) {
    if (!dst || cap == 0) return;
    if (!src) { dst[0] = 0; return; }
    wcsncpy_s(dst, cap, src, _TRUNCATE);
}

std::wstring join_path(const wchar_t* dir, const wchar_t* name) {
    std::wstring out(dir ? dir : L"");
    if (!out.empty() && out.back() != L'\\' && out.back() != L'/') out += L'\\';
    out += name;
    return out;
}

bool file_exists(const std::wstring& path) {
    const DWORD a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

std::wstring runtime_version_string(const std::wstring& path) {
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(path.c_str(), &handle);
    if (!size) return L"unknown";
    std::vector<uint8_t> data(size);
    if (!GetFileVersionInfoW(path.c_str(), 0, size, data.data())) return L"unknown";
    VS_FIXEDFILEINFO* info = nullptr;
    UINT len = 0;
    if (!VerQueryValueW(data.data(), L"\\", (void**)&info, &len) || !info) return L"unknown";
    wchar_t buf[64];
    swprintf_s(buf, L"%u.%u.%u.%u",
               HIWORD(info->dwFileVersionMS), LOWORD(info->dwFileVersionMS),
               HIWORD(info->dwFileVersionLS), LOWORD(info->dwFileVersionLS));
    return buf;
}

const char* ngx_result_name(uint32_t r) {
    switch (r) {
    case 0x1:        return "Success";
    case 0xBAD00000: return "FAIL_Fail";
    case 0xBAD00001: return "FAIL_FeatureNotSupported (architecture check; stock runtime on a pre-Blackwell GPU?)";
    case 0xBAD00002: return "FAIL_PlatformError (NGX core/module-name gate, or the driver rejected this runtime build)";
    case 0xBAD00004: return "FAIL_FeatureNotFound";
    case 0xBAD00005: return "FAIL_InvalidParameter";
    case 0xBAD0000B: return "FAIL_UnableToInitializeFeature";
    case 0xBAD0000C: return "FAIL_OutOfDate";
    case 0xBAD0000E: return "FAIL_NotInitialized";
    default:         return "NGX error";
    }
}

/* ------------------------------------------------------------------------- */
/* GPU: private D3D12 device + queue/allocator/list/fence                      */
/* ------------------------------------------------------------------------- */

struct Gpu {
    ID3D12Device*              device    = nullptr;
    ID3D12CommandQueue*        queue     = nullptr;
    ID3D12CommandAllocator*    allocator = nullptr;
    ID3D12GraphicsCommandList* list      = nullptr;
    ID3D12Fence*               fence     = nullptr;
    HANDLE                     fence_ev  = nullptr;
    UINT64                     fence_v   = 0;
    std::wstring               adapter_name;

    bool create() {
        HMODULE d3d12 = LoadLibraryW(L"d3d12.dll");
        HMODULE dxgi  = LoadLibraryW(L"dxgi.dll");
        auto create_device = d3d12
            ? reinterpret_cast<HRESULT (WINAPI*)(IDXGIAdapter*, D3D_FEATURE_LEVEL, REFIID, void**)>(
                  GetProcAddress(d3d12, "D3D12CreateDevice"))
            : nullptr;
        auto create_factory = dxgi
            ? reinterpret_cast<HRESULT (WINAPI*)(REFIID, void**)>(
                  GetProcAddress(dxgi, "CreateDXGIFactory1"))
            : nullptr;
        if (!create_device || !create_factory) return false;

        IDXGIFactory1* factory = nullptr;
        if (FAILED(create_factory(IID_PPV_ARGS(&factory)))) return false;

        IDXGIAdapter1* adapter = nullptr;
        for (UINT i = 0; factory->EnumAdapters1(i, &adapter) == S_OK; ++i) {
            DXGI_ADAPTER_DESC1 desc;
            adapter->GetDesc1(&desc);
            if (desc.VendorId == 0x10DE) {
                adapter_name = desc.Description;
                break;
            }
            adapter->Release();
            adapter = nullptr;
        }
        factory->Release();
        if (!adapter) return false;

        const HRESULT hr = create_device(adapter, D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device));
        adapter->Release();
        if (FAILED(hr)) return false;

        D3D12_COMMAND_QUEUE_DESC qd = {};
        if (FAILED(device->CreateCommandQueue(&qd, IID_PPV_ARGS(&queue))) ||
            FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
                                                  IID_PPV_ARGS(&allocator))) ||
            FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT,
                                             allocator, nullptr, IID_PPV_ARGS(&list))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)))) {
            return false;
        }
        list->Close();
        fence_ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return fence_ev != nullptr;
    }

    bool begin() {
        return SUCCEEDED(allocator->Reset()) && SUCCEEDED(list->Reset(allocator, nullptr));
    }

    bool submit_and_wait() {
        if (FAILED(list->Close())) return false;
        ID3D12CommandList* lists[] = { list };
        queue->ExecuteCommandLists(1, lists);
        const UINT64 value = ++fence_v;
        if (FAILED(queue->Signal(fence, value))) return false;
        if (fence->GetCompletedValue() < value) {
            fence->SetEventOnCompletion(value, fence_ev);
            WaitForSingleObject(fence_ev, 60000);
        }
        return fence->GetCompletedValue() >= value;
    }

    ID3D12Resource* texture(UINT w, UINT h, DXGI_FORMAT format, bool uav,
                            D3D12_RESOURCE_STATES initial) {
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC desc = {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        desc.Width = w;
        desc.Height = h;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.Format = format;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
        desc.Flags = uav ? D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS : D3D12_RESOURCE_FLAG_NONE;
        ID3D12Resource* res = nullptr;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                                   initial, nullptr, IID_PPV_ARGS(&res)))) {
            return nullptr;
        }
        return res;
    }

    ID3D12Resource* buffer(UINT64 size, D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES initial) {
        D3D12_HEAP_PROPERTIES heap = {};
        heap.Type = type;
        D3D12_RESOURCE_DESC desc = {};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = size;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.Format = DXGI_FORMAT_UNKNOWN;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ID3D12Resource* res = nullptr;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                                   initial, nullptr, IID_PPV_ARGS(&res)))) {
            return nullptr;
        }
        return res;
    }

    void destroy() {
        release_com(list);
        release_com(allocator);
        release_com(queue);
        release_com(fence);
        release_com(device);
        if (fence_ev) { CloseHandle(fence_ev); fence_ev = nullptr; }
        fence_v = 0;
    }
};

D3D12_RESOURCE_BARRIER barrier_transition(ID3D12Resource* res,
                                          D3D12_RESOURCE_STATES before,
                                          D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER b = {};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = res;
    b.Transition.StateBefore = before;
    b.Transition.StateAfter = after;
    b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    return b;
}

D3D12_TEXTURE_COPY_LOCATION placed_location(ID3D12Resource* res, UINT w, UINT h,
                                            DXGI_FORMAT format, UINT pitch) {
    D3D12_TEXTURE_COPY_LOCATION l = {};
    l.pResource = res;
    l.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    l.PlacedFootprint.Footprint.Format = format;
    l.PlacedFootprint.Footprint.Width = w;
    l.PlacedFootprint.Footprint.Height = h;
    l.PlacedFootprint.Footprint.Depth = 1;
    l.PlacedFootprint.Footprint.RowPitch = pitch;
    return l;
}

D3D12_TEXTURE_COPY_LOCATION whole_location(ID3D12Resource* res) {
    D3D12_TEXTURE_COPY_LOCATION l = {};
    l.pResource = res;
    l.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    l.SubresourceIndex = 0;
    return l;
}

/* ------------------------------------------------------------------------- */
/* Feature + server state                                                     */
/* ------------------------------------------------------------------------- */

/* Per-frame neural controls, captured from FlNrOptions at init time. */
struct Controls {
    uint32_t style = 1;
    float    intensity = 0.35f;
    float    local_tone = 1.0f;
    float    local_structure = 1.0f;
    float    skin_structure = 1.0f;
    uint32_t auto_mask = 1;
    float    exposure = 1.0f;
};

struct Feature {
    int32_t  width = 0, height = 0;
    int32_t  work_w = 0, work_h = 0;
    UINT     io_pitch = 0, work_pitch = 0;
    uint32_t passes = 1;
    uint32_t temporal = 0;
    bool     first_frame = true;

    ID3D12Resource*    color    = nullptr; /* R8G8B8A8 io-sized (COPY_DEST) */
    ID3D12Resource*    motion   = nullptr; /* R16G16_FLOAT work (SHADER_RES)*/
    ID3D12Resource*    output   = nullptr; /* R8G8B8A8 io UAV              */
    ID3D12Resource*    up_color = nullptr; /* upload staging               */
    ID3D12Resource*    readback = nullptr; /* readback staging             */
    NVSDK_NGX_Handle*  handle   = nullptr;
};

struct Server {
    Gpu gpu;
    HMODULE core = nullptr, runtime = nullptr;
    PFN_NGX_INIT         p_init      = nullptr;
    PFN_NGX_ALLOC_PARAMS p_alloc     = nullptr;
    PFN_NGX_INIT_EXT     p_init_ext  = nullptr;
    PFN_NGX_CREATE       p_create    = nullptr;
    PFN_NGX_EVAL         p_eval      = nullptr;
    PFN_NGX_RELEASE      p_release   = nullptr;
    PFN_NGX_SHUTDOWN12   p_shutdown  = nullptr;
    NgxParams  params;
    Controls   controls;
    Feature    feature;
    bool       initialized = false;
    std::wstring core_path, runtime_path;

    FlNrStatus status;
    uint32_t   last_ngx = FLNR_NGX_SUCCESS;

    Server() { memset(&status, 0, sizeof(status)); }

    int32_t init(const FlNrOptions* opt, const wchar_t* native_dir,
                 const wchar_t* log_dir, char* err, int32_t errlen);
    int32_t build_feature(const FlNrOptions* opt, char* err, int32_t errlen);
    int32_t process(const uint8_t* rgb_in, int32_t in_stride,
                    uint8_t* rgb_out, int32_t out_stride,
                    char* err, int32_t errlen);
    void shutdown();
    void sync_status();
};

Server g_server;

void Server::sync_status() {
    status.initialized = initialized ? 1 : 0;
    status.last_ngx_result = last_ngx;
    status.width = feature.width;
    status.height = feature.height;
    status.work_width = feature.work_w;
    status.work_height = feature.work_h;
    status.passes_active = feature.passes;
    wcopy(status.gpu, 128, gpu.adapter_name.c_str());
    wcopy(status.core_path, 260, core_path.c_str());
    wcopy(status.runtime_path, 260, runtime_path.c_str());
    strncpy_s(status.backend, sizeof(status.backend), "ngx-core+dlssnr", _TRUNCATE);
}

int32_t Server::init(const FlNrOptions* opt, const wchar_t* native_dir,
                     const wchar_t* log_dir, char* err, int32_t errlen) {
    shutdown();
    memset(&status, 0, sizeof(status));
    last_ngx = FLNR_NGX_SUCCESS;

    if (!opt || !native_dir || !log_dir) {
        set_err(err, errlen, "invalid arguments");
        status.last_error = FLNR_ERR_BAD_ARG;
        return FLNR_ERR_BAD_ARG;
    }
    controls.style = opt->style;
    controls.intensity = opt->intensity;
    controls.local_tone = opt->local_tone;
    controls.local_structure = opt->local_structure;
    controls.skin_structure = opt->skin_structure;
    controls.auto_mask = opt->auto_mask;
    controls.exposure = opt->exposure;

    /* 1. Private D3D12 device on the NVIDIA adapter. */
    if (!gpu.create()) {
        set_err(err, errlen, "could not create a D3D12 device on an NVIDIA adapter");
        status.last_error = FLNR_ERR_NO_NVIDIA_GPU;
        sync_status();
        return FLNR_ERR_NO_NVIDIA_GPU;
    }

    /* 2. NGX core: user-provided override first, then the driver's copy. */
    core_path = join_path(native_dir, L"nvngx.dll");
    if (file_exists(core_path)) core = LoadLibraryW(core_path.c_str());
    if (!core) {
        core_path = join_path(native_dir, L"_nvngx.dll");
        if (file_exists(core_path)) core = LoadLibraryW(core_path.c_str());
    }
    if (!core) {
        wchar_t program_files[MAX_PATH] = L"";
        GetEnvironmentVariableW(L"ProgramFiles", program_files, MAX_PATH);
        core_path = std::wstring(program_files) +
            L"\\NVIDIA Corporation\\NVIDIA NGX\\nvngx.dll";
        if (file_exists(core_path)) core = LoadLibraryW(core_path.c_str());
    }
    if (!core) {
        core = LoadLibraryW(L"nvngx.dll");
        core_path = L"nvngx.dll (search path)";
    }
    if (!core) {
        set_err(err, errlen,
                "NVIDIA NGX core (nvngx.dll) not found - install or update the NVIDIA driver");
        status.last_error = FLNR_ERR_CORE_LOAD;
        sync_status();
        return FLNR_ERR_CORE_LOAD;
    }

    p_init = reinterpret_cast<PFN_NGX_INIT>(
        GetProcAddress(core, "NVSDK_NGX_D3D12_Init"));
    p_alloc = reinterpret_cast<PFN_NGX_ALLOC_PARAMS>(
        GetProcAddress(core, "NVSDK_NGX_D3D12_AllocateParameters"));
    p_shutdown = reinterpret_cast<PFN_NGX_SHUTDOWN12>(
        GetProcAddress(core, "NVSDK_NGX_D3D12_Shutdown"));
    if (!p_init || !p_alloc) {
        set_err(err, errlen, "NGX core is missing NVSDK_NGX_D3D12_Init/AllocateParameters");
        status.last_error = FLNR_ERR_CORE_LOAD;
        sync_status();
        return FLNR_ERR_CORE_LOAD;
    }

    NVSDK_NGX_Result r = p_init(0x1000000ULL, log_dir, gpu.device,
                                nullptr, FLNR_NGX_VERSION_API);
    last_ngx = r;
    if (FLNR_NGX_FAILED(r)) {
        set_err(err, errlen, "NVSDK_NGX_D3D12_Init failed: %s (0x%08X)",
                ngx_result_name(r), r);
        status.last_error = FLNR_ERR_CORE_INIT;
        sync_status();
        return FLNR_ERR_CORE_INIT;
    }
    r = p_alloc(&params.obj);
    last_ngx = r;
    if (FLNR_NGX_FAILED(r) || !params.obj) {
        set_err(err, errlen, "NVSDK_NGX_D3D12_AllocateParameters failed: 0x%08X", r);
        status.last_error = FLNR_ERR_CORE_INIT;
        sync_status();
        return FLNR_ERR_CORE_INIT;
    }

    /* 3. User-supplied DLSSNR runtime. */
    runtime_path = join_path(native_dir, L"nvngx_dlssnr.dll");
    runtime = LoadLibraryExW(runtime_path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!runtime) {
        set_err(err, errlen,
                "nvngx_dlssnr.dll failed to load (win32 error %lu) - check that the file is "
                "a complete DLSSNR runtime and that its dependencies are present",
                GetLastError());
        status.last_error = FLNR_ERR_RUNTIME_LOAD;
        sync_status();
        return FLNR_ERR_RUNTIME_LOAD;
    }
    p_init_ext = reinterpret_cast<PFN_NGX_INIT_EXT>(
        GetProcAddress(runtime, "NVSDK_NGX_D3D12_Init_Ext"));
    p_create = reinterpret_cast<PFN_NGX_CREATE>(
        GetProcAddress(runtime, "NVSDK_NGX_D3D12_CreateFeature"));
    p_eval = reinterpret_cast<PFN_NGX_EVAL>(
        GetProcAddress(runtime, "NVSDK_NGX_D3D12_EvaluateFeature"));
    p_release = reinterpret_cast<PFN_NGX_RELEASE>(
        GetProcAddress(runtime, "NVSDK_NGX_D3D12_ReleaseFeature"));
    if (!p_init_ext || !p_create || !p_eval || !p_release) {
        set_err(err, errlen, "nvngx_dlssnr.dll is missing NVSDK_NGX_D3D12_* exports");
        status.last_error = FLNR_ERR_RUNTIME_LOAD;
        sync_status();
        return FLNR_ERR_RUNTIME_LOAD;
    }

    r = p_init_ext(0x1000000ULL, log_dir, gpu.device, FLNR_NGX_VERSION_API, params.obj);
    last_ngx = r;
    if (FLNR_NGX_FAILED(r)) {
        set_err(err, errlen, "nvngx_dlssnr.dll Init_Ext failed: %s (0x%08X)",
                ngx_result_name(r), r);
        status.last_error = FLNR_ERR_RUNTIME_INIT;
        sync_status();
        return FLNR_ERR_RUNTIME_INIT;
    }

    wcopy(status.runtime_version, 64, runtime_version_string(runtime_path).c_str());
    sync_status();

    /* 4. Feature creation with the real frame size. */
    const int32_t rc = build_feature(opt, err, errlen);
    if (rc != FLNR_OK) return rc;

    initialized = true;
    sync_status();
    return FLNR_OK;
}

int32_t Server::build_feature(const FlNrOptions* opt, char* err, int32_t errlen) {
    if (feature.handle && p_release) {
        p_release(feature.handle);
        feature.handle = nullptr;
    }
    release_com(feature.color);
    release_com(feature.motion);
    release_com(feature.output);
    release_com(feature.up_color);
    release_com(feature.readback);

    Feature f;
    f.width = opt->width;
    f.height = opt->height;
    f.work_w = opt->work_width > 0 ? opt->work_width : opt->width;
    f.work_h = opt->work_height > 0 ? opt->work_height : opt->height;
    f.passes = opt->passes >= 2 ? 2u : 1u;
    f.temporal = opt->temporal;
    f.first_frame = true;

    if (f.width <= 0 || f.height <= 0 || f.work_w <= 0 || f.work_h <= 0) {
        set_err(err, errlen, "invalid frame/work resolution");
        status.last_error = FLNR_ERR_BAD_ARG;
        return FLNR_ERR_BAD_ARG;
    }

    const bool upscaling = (f.work_w != f.width) || (f.work_h != f.height);
    const float ratio = (float)f.work_w / (float)f.width;

    params.clear();
    params.set_uint("CreationNodeMask", 1u);
    params.set_uint("VisibilityNodeMask", 1u);
    params.set_uint("DLSSNR.Width", (unsigned int)f.work_w);
    params.set_uint("DLSSNR.Height", (unsigned int)f.work_h);
    params.set_uint("DLSSNR.InputWidth", (unsigned int)f.width);
    params.set_uint("DLSSNR.InputHeight", (unsigned int)f.height);
    params.set_uint("DLSSNR.OutputWidth", (unsigned int)f.width);
    params.set_uint("DLSSNR.OutputHeight", (unsigned int)f.height);
    params.set_uint("DLSSNR.Output.Width", (unsigned int)f.width);
    params.set_uint("DLSSNR.Output.Height", (unsigned int)f.height);
    params.set_uint("DLSSNR.Upscaling", upscaling ? 1u : 0u);
    params.set_float("DLSSNR.Scale", ratio);
    params.set_float("DLSSNR.ScalingRatio", ratio);
    params.set_uint("DLSSNR.Hint.Render.Preset", opt->preset);
    params.set_uint("DLSS.Feature.Create.Flags", 0u);

    if (!gpu.begin()) {
        set_err(err, errlen, "command list reset failed");
        status.last_error = FLNR_ERR_GPU;
        return FLNR_ERR_GPU;
    }
    NVSDK_NGX_Result r = p_create(gpu.list, FLNR_FEATURE_DLSSNR, params.obj, &f.handle);
    last_ngx = r;
    const bool submitted = gpu.submit_and_wait();
    if (FLNR_NGX_FAILED(r) || !f.handle || !submitted) {
        if (FLNR_NGX_FAILED(r) || !f.handle) {
            set_err(err, errlen, "NGX CreateFeature(18) failed: %s (0x%08X)",
                    ngx_result_name(r), r);
        } else {
            set_err(err, errlen, "GPU submission after CreateFeature failed");
        }
        if (f.handle && p_release) { p_release(f.handle); f.handle = nullptr; }
        status.last_error = FLNR_ERR_FEATURE;
        sync_status();
        return FLNR_ERR_FEATURE;
    }

    f.io_pitch = align256((UINT)(f.width * 4));
    f.work_pitch = align256((UINT)(f.work_w * 4));
    f.color = gpu.texture((UINT)f.width, (UINT)f.height, DXGI_FORMAT_R8G8B8A8_UNORM, false,
                          D3D12_RESOURCE_STATE_COPY_DEST);
    f.motion = gpu.texture((UINT)f.work_w, (UINT)f.work_h, DXGI_FORMAT_R16G16_FLOAT, true,
                           D3D12_RESOURCE_STATE_COPY_DEST);
    f.output = gpu.texture((UINT)f.width, (UINT)f.height, DXGI_FORMAT_R8G8B8A8_UNORM, true,
                           D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    f.up_color = gpu.buffer((UINT64)f.io_pitch * (UINT64)f.height, D3D12_HEAP_TYPE_UPLOAD,
                            D3D12_RESOURCE_STATE_GENERIC_READ);
    f.readback = gpu.buffer((UINT64)f.io_pitch * (UINT64)f.height, D3D12_HEAP_TYPE_READBACK,
                            D3D12_RESOURCE_STATE_COPY_DEST);
    if (!f.color || !f.motion || !f.output || !f.up_color || !f.readback) {
        set_err(err, errlen, "texture/staging creation failed at %dx%d", f.width, f.height);
        if (f.handle) p_release(f.handle);
        release_com(f.color); release_com(f.motion); release_com(f.output);
        release_com(f.up_color); release_com(f.readback);
        status.last_error = FLNR_ERR_GPU;
        sync_status();
        return FLNR_ERR_GPU;
    }
    feature = f;

    /* Zero motion vectors (external capture has no engine MVs): upload once. */
    if (!gpu.begin()) {
        set_err(err, errlen, "command list reset failed (motion upload)");
        status.last_error = FLNR_ERR_GPU;
        return FLNR_ERR_GPU;
    }
    ID3D12Resource* up_motion = gpu.buffer((UINT64)feature.work_pitch * (UINT64)feature.work_h,
                                           D3D12_HEAP_TYPE_UPLOAD,
                                           D3D12_RESOURCE_STATE_GENERIC_READ);
    if (!up_motion) {
        set_err(err, errlen, "motion staging creation failed");
        status.last_error = FLNR_ERR_GPU;
        return FLNR_ERR_GPU;
    }
    void* mapped = nullptr;
    up_motion->Map(0, nullptr, &mapped);
    memset(mapped, 0, (size_t)feature.work_pitch * (size_t)feature.work_h);
    up_motion->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION m_dst = whole_location(feature.motion);
    D3D12_TEXTURE_COPY_LOCATION m_src = placed_location(up_motion, (UINT)feature.work_w,
                                                        (UINT)feature.work_h,
                                                        DXGI_FORMAT_R16G16_FLOAT,
                                                        feature.work_pitch);
    gpu.list->CopyTextureRegion(&m_dst, 0, 0, 0, &m_src, nullptr);
    D3D12_RESOURCE_BARRIER m_bar = barrier_transition(feature.motion,
                                                      D3D12_RESOURCE_STATE_COPY_DEST,
                                                      D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    gpu.list->ResourceBarrier(1, &m_bar);
    const bool motion_ok = gpu.submit_and_wait();
    release_com(up_motion);
    if (!motion_ok) {
        set_err(err, errlen, "motion upload failed");
        status.last_error = FLNR_ERR_GPU;
        return FLNR_ERR_GPU;
    }

    sync_status();
    return FLNR_OK;
}

int32_t Server::process(const uint8_t* rgb_in, int32_t in_stride,
                        uint8_t* rgb_out, int32_t out_stride,
                        char* err, int32_t errlen) {
    if (!initialized || !feature.handle) {
        set_err(err, errlen, "feature not initialized");
        status.last_error = FLNR_ERR_FEATURE;
        return FLNR_ERR_FEATURE;
    }
    const int32_t w = feature.width, h = feature.height;
    const size_t row_bytes = (size_t)w * 3u;
    if (!rgb_in || !rgb_out || in_stride < (int32_t)row_bytes || out_stride < (int32_t)row_bytes) {
        set_err(err, errlen, "invalid frame buffer/stride");
        status.last_error = FLNR_ERR_BAD_ARG;
        return FLNR_ERR_BAD_ARG;
    }

    /* Upload: RGB -> RGBA row copy into the mapped upload buffer. */
    {
        void* mapped = nullptr;
        feature.up_color->Map(0, nullptr, &mapped);
        uint8_t* dst = static_cast<uint8_t*>(mapped);
        for (int32_t y = 0; y < h; ++y) {
            const uint8_t* src = rgb_in + (size_t)y * (size_t)in_stride;
            uint8_t* row = dst + (size_t)y * feature.io_pitch;
            for (int32_t x = 0; x < w; ++x) {
                row[x * 4 + 0] = src[x * 3 + 0];
                row[x * 4 + 1] = src[x * 3 + 1];
                row[x * 4 + 2] = src[x * 3 + 2];
                row[x * 4 + 3] = 255;
            }
        }
        feature.up_color->Unmap(0, nullptr);
    }

    if (!gpu.begin()) {
        set_err(err, errlen, "command list reset failed");
        status.last_error = FLNR_ERR_GPU;
        status.frames_failed++;
        return FLNR_ERR_GPU;
    }
    ID3D12GraphicsCommandList* list = gpu.list;

    D3D12_TEXTURE_COPY_LOCATION tex_dst = whole_location(feature.color);
    D3D12_TEXTURE_COPY_LOCATION tex_src = placed_location(feature.up_color, (UINT)w, (UINT)h,
                                                          DXGI_FORMAT_R8G8B8A8_UNORM,
                                                          feature.io_pitch);
    list->CopyTextureRegion(&tex_dst, 0, 0, 0, &tex_src, nullptr);
    D3D12_RESOURCE_BARRIER b_in = barrier_transition(feature.color,
                                                     D3D12_RESOURCE_STATE_COPY_DEST,
                                                     D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    list->ResourceBarrier(1, &b_in);

    /* Evaluate parameters (contract confirmed by measured implementations). */
    const bool reset = (feature.temporal == 0) || feature.first_frame;
    params.clear();
    params.set_resource("DLSSNR.Color", feature.color);
    params.set_resource("DLSSNR.Output", feature.output);
    params.set_resource("DLSSNR.MVec", feature.motion);
    params.set_uint("DLSSNR.ColorSubrectBaseX", 0u);
    params.set_uint("DLSSNR.ColorSubrectBaseY", 0u);
    params.set_uint("DLSSNR.ColorSubrectWidth", (unsigned int)w);
    params.set_uint("DLSSNR.ColorSubrectHeight", (unsigned int)h);
    params.set_uint("DLSSNR.MVecSubrectBaseX", 0u);
    params.set_uint("DLSSNR.MVecSubrectBaseY", 0u);
    params.set_uint("DLSSNR.MVecSubrectWidth", (unsigned int)feature.work_w);
    params.set_uint("DLSSNR.MVecSubrectHeight", (unsigned int)feature.work_h);
    params.set_uint("DLSSNR.OutputSubrectBaseX", 0u);
    params.set_uint("DLSSNR.OutputSubrectBaseY", 0u);
    params.set_uint("DLSSNR.OutputSubrectWidth", (unsigned int)w);
    params.set_uint("DLSSNR.OutputSubrectHeight", (unsigned int)h);
    params.set_float("DLSSNR.MVecScaleX", 1.0f);
    params.set_float("DLSSNR.MVecScaleY", 1.0f);
    params.set_uint("DLSSNR.Enabled", 1u);
    params.set_uint("DLSSNR.Reset", reset ? 1u : 0u);
    params.set_uint("DLSSNR.Style", controls.style);
    params.set_float("DLSSNR.Intensity", controls.intensity);
    params.set_float("DLSSNR.LocalToneStrength", controls.local_tone);
    params.set_float("DLSSNR.LocalStructureStrength", controls.local_structure);
    params.set_float("DLSSNR.SkinStructureStrength", controls.skin_structure);
    params.set_uint("DLSSNR.UseAutoMask", controls.auto_mask);
    params.set_float("DLSS.Pre.Exposure", 1.0f);
    params.set_float("DLSS.Exposure.Scale", controls.exposure);

    NVSDK_NGX_Result eval_result = FLNR_NGX_SUCCESS;
    for (uint32_t pass = 0; pass < feature.passes; ++pass) {
        eval_result = p_eval(list, feature.handle, params.obj, nullptr);
        last_ngx = eval_result;
        if (FLNR_NGX_FAILED(eval_result)) break;
        if (pass + 1 < feature.passes) {
            /* Feed the output back as the color input of the next pass. */
            D3D12_RESOURCE_BARRIER bars[2] = {
                barrier_transition(feature.output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                                   D3D12_RESOURCE_STATE_COPY_SOURCE),
                barrier_transition(feature.color, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                                   D3D12_RESOURCE_STATE_COPY_DEST)
            };
            list->ResourceBarrier(2, bars);
            list->CopyResource(feature.color, feature.output);
            D3D12_RESOURCE_BARRIER back[2] = {
                barrier_transition(feature.output, D3D12_RESOURCE_STATE_COPY_SOURCE,
                                   D3D12_RESOURCE_STATE_UNORDERED_ACCESS),
                barrier_transition(feature.color, D3D12_RESOURCE_STATE_COPY_DEST,
                                   D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE)
            };
            list->ResourceBarrier(2, back);
        }
    }

    /* Read the result back (leave color in COPY_DEST for the next frame). */
    D3D12_RESOURCE_BARRIER out_bars[2] = {
        barrier_transition(feature.output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                           D3D12_RESOURCE_STATE_COPY_SOURCE),
        barrier_transition(feature.color, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                           D3D12_RESOURCE_STATE_COPY_DEST)
    };
    list->ResourceBarrier(2, out_bars);
    D3D12_TEXTURE_COPY_LOCATION rb_dst = placed_location(feature.readback, (UINT)w, (UINT)h,
                                                          DXGI_FORMAT_R8G8B8A8_UNORM,
                                                          feature.io_pitch);
    D3D12_TEXTURE_COPY_LOCATION rb_src = whole_location(feature.output);
    list->CopyTextureRegion(&rb_dst, 0, 0, 0, &rb_src, nullptr);
    D3D12_RESOURCE_BARRIER restore = barrier_transition(feature.output,
                                                        D3D12_RESOURCE_STATE_COPY_SOURCE,
                                                        D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    list->ResourceBarrier(1, &restore);

    if (!gpu.submit_and_wait()) {
        set_err(err, errlen, "GPU submission failed");
        status.last_error = FLNR_ERR_GPU;
        status.frames_failed++;
        sync_status();
        return FLNR_ERR_GPU;
    }
    if (FLNR_NGX_FAILED(eval_result)) {
        set_err(err, errlen, "NGX EvaluateFeature failed: %s (0x%08X)",
                ngx_result_name(eval_result), eval_result);
        status.last_error = FLNR_ERR_FEATURE;
        status.frames_failed++;
        sync_status();
        return FLNR_ERR_FEATURE;
    }

    /* Readback: RGBA -> RGB row copy. */
    {
        D3D12_RANGE range = { 0, (SIZE_T)feature.io_pitch * (SIZE_T)h };
        void* mapped = nullptr;
        feature.readback->Map(0, &range, &mapped);
        const uint8_t* src = static_cast<const uint8_t*>(mapped);
        for (int32_t y = 0; y < h; ++y) {
            const uint8_t* row = src + (size_t)y * feature.io_pitch;
            uint8_t* dst = rgb_out + (size_t)y * (size_t)out_stride;
            for (int32_t x = 0; x < w; ++x) {
                dst[x * 3 + 0] = row[x * 4 + 0];
                dst[x * 3 + 1] = row[x * 4 + 1];
                dst[x * 3 + 2] = row[x * 4 + 2];
            }
        }
        D3D12_RANGE none = { 0, 0 };
        feature.readback->Unmap(0, &none);
    }

    feature.first_frame = false;
    status.frames_ok++;
    sync_status();
    return FLNR_OK;
}

void Server::shutdown() {
    if (feature.handle && p_release) {
        p_release(feature.handle);
        feature.handle = nullptr;
    }
    release_com(feature.color);
    release_com(feature.motion);
    release_com(feature.output);
    release_com(feature.up_color);
    release_com(feature.readback);
    feature = Feature();
    if (p_shutdown) {
        p_shutdown();
        p_shutdown = nullptr;
    }
    if (core) {
        FreeLibrary(core);
        core = nullptr;
    }
    if (runtime) {
        FreeLibrary(runtime);
        runtime = nullptr;
    }
    p_init = nullptr;
    p_alloc = nullptr;
    p_init_ext = nullptr;
    p_create = nullptr;
    p_eval = nullptr;
    p_release = nullptr;
    params.obj = nullptr;
    gpu.destroy();
    initialized = false;
}

} // namespace

/* ------------------------------------------------------------------------- */
/* Exported C API                                                             */
/* ------------------------------------------------------------------------- */

extern "C" {

FLNR_API int32_t FLNR_CALL flnr_init(const FlNrOptions* options,
                                     const wchar_t* native_dir,
                                     const wchar_t* log_dir,
                                     FlNrStatus* out_status,
                                     char* errbuf, int32_t errlen) {
    if (!g_lock_ready) {
        InitializeCriticalSection(&g_lock);
        g_lock_ready = true;
    }
    EnterCriticalSection(&g_lock);
    const int32_t rc = g_server.init(options, native_dir, log_dir, errbuf, errlen);
    if (out_status) {
        g_server.sync_status();
        *out_status = g_server.status;
    }
    LeaveCriticalSection(&g_lock);
    return rc;
}

FLNR_API int32_t FLNR_CALL flnr_process(const uint8_t* rgb_in, int32_t in_stride,
                                        uint8_t* rgb_out, int32_t out_stride,
                                        FlNrStatus* out_status,
                                        char* errbuf, int32_t errlen) {
    if (!g_lock_ready) {
        InitializeCriticalSection(&g_lock);
        g_lock_ready = true;
    }
    EnterCriticalSection(&g_lock);
    const int32_t rc = g_server.process(rgb_in, in_stride, rgb_out, out_stride, errbuf, errlen);
    if (out_status) {
        g_server.sync_status();
        *out_status = g_server.status;
    }
    LeaveCriticalSection(&g_lock);
    return rc;
}

FLNR_API int32_t FLNR_CALL flnr_get_status(FlNrStatus* out_status) {
    if (!g_lock_ready) {
        InitializeCriticalSection(&g_lock);
        g_lock_ready = true;
    }
    EnterCriticalSection(&g_lock);
    if (out_status) {
        g_server.sync_status();
        *out_status = g_server.status;
    }
    LeaveCriticalSection(&g_lock);
    return FLNR_OK;
}

FLNR_API void FLNR_CALL flnr_shutdown(void) {
    if (!g_lock_ready) {
        InitializeCriticalSection(&g_lock);
        g_lock_ready = true;
    }
    EnterCriticalSection(&g_lock);
    g_server.shutdown();
    LeaveCriticalSection(&g_lock);
}

} /* extern "C" */
