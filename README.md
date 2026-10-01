# Free Lossless: Open AI Frame Generation

![Logo]()

Free Lossless is a high-performance, non-intrusive Frame Generation tool for Windows. It enhances game fluidity by creating synthetic frames using AI, similar to technologies like DLSS 3 or LSFG, but without requiring any modification to the game's code.

## How it works (Simple words)

Unlike most frame generation tools that need to be "inside" the game (using its engine data), Free Lossless works from the **outside**:

1.  **High-Speed Capture**: It looks at your screen and "captures" the game window at high speed (using DXCAM or BitBlt).
2.  **AI Interpolation**: It uses the **RIFE AI model** to analyze the movement between two real frames and calculates exactly how the intermediate frame would look.
3.  **Transparent Overlay**: It creates a completely transparent window (an "overlay") that sits on top of your game. It displays the original and the new AI-generated frames in perfect sequence.

**No Injection**: Since it doesn't inject files, hook into the game process, or modify the GPU pipeline, it is extremely safe and compatible with almost any application.

## Why use it?

*   **No Game Access**: Perfect for older games, emulators, or modern titles that don't support DLSS/FSR frame generation natively.
*   **Engine Independent**: It works regardless of the graphics engine (DirectX, OpenGL, Vulkan).
*   **Lossless Approach**: No need to lower your internal game resolution unless you want extra performance.

---

## Download the Windows app (no local build needed)

GitHub Actions builds a standalone Windows x64 executable on every push and pull
request to `master`. Python does **not** need to be installed to run the downloaded app.

1. Open the repository's **Actions** tab and select **Build Windows executable**.
2. Open a successful run for the branch/commit you want.
3. Under **Artifacts**, download **FreeLossless-Windows-x64** (sign in to GitHub).
4. Extract the ZIP and run `FreeLossless.exe`.

Artifacts are kept for 30 days. After the workflow is merged into the default
branch, you can also use **Run workflow** to build it manually. The executable is
unsigned, so Windows SmartScreen may show a warning; only run builds you trust.

## Choose what to capture

- **Janela (app/jogo)**: select a visible application/game window.
- **Display/Monitor**: select an entire monitor, such as **Display 1** or
  **Display 2**. The actual primary monitor is marked **Monitor principal**; display
  numbers follow Windows and the primary monitor is not necessarily Display 1.
- Use **Atualizar** after opening a window or connecting/disconnecting a monitor.
- **Backend de captura** still selects DXCAM or BitBlt; it is independent of the
  capture source. DXCAM falls back to BitBlt if an output is unavailable or a window
  spans monitors.
- **Fullscreen** puts a borderless overlay on the selected source's monitor,
  rather than always using the primary screen. Press **F11** to return to the menu.

## Interface e salvamento automático

O menu usa um tema escuro, com painéis separados para a fonte de captura e os
ajustes do overlay. Há atalhos de FPS, controles de ativação e uma área de ajustes
com rolagem para manter todas as opções acessíveis em telas menores.

- As alterações são salvas automaticamente após uma breve pausa nos ajustes.
- **Iniciar overlay**, **Sair** e o botão de fechar a janela salvam imediatamente,
  sem precisar de um botão de confirmação.
- Ao voltar com **F11** ou reabrir o app, são restaurados o tipo de fonte, backend,
  FPS, escala, algoritmo, nitidez, geração de quadros, motor, Ultra Smooth, modo de
  desempenho e baixa latência.
- A última janela e o último monitor selecionados também são lembrados. A seleção
  só é restaurada quando a fonte está disponível: monitores são identificados pelo
  dispositivo e janelas pelo título/processo. Se o título mudar, o processo só é
  usado quando há uma única janela correspondente. Identificadores de janelas
  (`HWND`) e posições antigas de monitores **não** são reutilizados.

No Windows, as preferências ficam em
`%LOCALAPPDATA%\FreeLossless\settings.json` (com `%APPDATA%` como alternativa),
independentemente da pasta do executável. Em outros sistemas, o módulo de
preferências respeita `$XDG_CONFIG_HOME/free-lossless/settings.json` ou
`~/.config/free-lossless/settings.json`; a captura e o overlay continuam exclusivos
para Windows.

A gravação é atômica para preservar o último arquivo em caso de falha. Se o arquivo
estiver inválido ou ilegível, o menu abre com os padrões e mostra um aviso no status.
Se não for possível salvar, o app informa o erro em vez de fechar inesperadamente.

## Setup Guide (developers / running from source)

### 1. Create a Virtual Environment
```powershell
python -m venv venv
```

### 2. Activate the Environment
```powershell
.\venv\Scripts\Activate.ps1
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Run the Application
```powershell
python main.py
```

## Building the Executable Locally (optional)
The Actions workflow runs this same command on Windows. To build locally:
```powershell
python build_app.py
```
The executable will be generated at `dist/FreeLossless.exe`, including the bundled models.

---

**Hardware Support**: For the best experience with the AI engine, the app utilizes **DirectML**. This ensures high-performance acceleration on almost any modern GPU (NVIDIA, AMD, or Intel) under Windows.
