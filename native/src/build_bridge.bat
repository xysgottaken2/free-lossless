@echo off
REM Build freelossless-nvngx.dll (Free Lossless DLSS 5 bridge) with MSVC.
REM
REM The output NAME must keep "nvngx.dll" as a substring - the DLSSNR runtime
REM refuses calls from modules whose path does not contain it (0xBAD00002).
REM
REM Usage (from a "x64 Native Tools" prompt, or via CI which calls vcvars64):
REM   native\src\build_bridge.bat [output_dir]
REM Output: <output_dir>\freelossless-nvngx.dll  (default: native\)
REM Also writes <output_dir>\build_bridge.log with the compiler output.

setlocal enabledelayedexpansion

REM %~dp0 ends with a backslash; strip it so quoted args do not end in \"
set "SRC_DIR=%~dp0"
set "SRC_DIR=%SRC_DIR:~0,-1%"

set "OUT_DIR=%SRC_DIR%\.."
if not "%~1"=="" set "OUT_DIR=%~1"

where cl >nul 2>nul
if errorlevel 1 (
    echo [build_bridge] cl.exe not found - run from an MSVC x64 developer prompt.
    exit /b 1
)

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
if not exist "%OUT_DIR%\build_bridge_objs" mkdir "%OUT_DIR%\build_bridge_objs"

set "LOG=%OUT_DIR%\build_bridge.log"

cl /nologo /std:c++17 /O2 /W3 /EHsc /DWIN32 /D_WINDOWS /DNDEBUG ^
   /I"%SRC_DIR%" ^
   /Fo"%OUT_DIR%\build_bridge_objs\\" ^
   /Fe"%OUT_DIR%\freelossless-nvngx.dll" ^
   /LD "%SRC_DIR%\flnr_bridge.cpp" ^
   /link /DEF:"%SRC_DIR%\flnr_bridge.def" d3d12.lib dxgi.lib version.lib user32.lib advapi32.lib > "%LOG%" 2>&1
set "CL_RESULT=%errorlevel%"

type "%LOG%"

if not "%CL_RESULT%"=="0" (
    echo [build_bridge] FAILED - compiler exit code %CL_RESULT%. See %LOG%
    exit /b 1
)
if not exist "%OUT_DIR%\freelossless-nvngx.dll" (
    echo [build_bridge] FAILED - output DLL missing. See %LOG%
    exit /b 1
)
echo [build_bridge] Built %OUT_DIR%\freelossless-nvngx.dll
exit /b 0
