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

- O painel de status do overlay (atalho de FPS) também foi modernizado: FPS em
  destaque, etiquetas de estado para FSR, AI, modo e a origem do frame (`FG` para
  frames gerados, `LIVE` para captura direta), e a dica do atalho de parada. O
  conteúdo é renderizado apenas quando o status muda, para não pesar no frame.
- **Geração de frames (x2 a x20)**: o slider define quantos frames cada par capturado
  se torna — x2 (padrão) gera 1 frame intermediário por par, x4 gera 3, x6 gera 5 e
  assim por diante. A captura passa a trabalhar a `FPS ÷ multiplicador` para manter a
  saída no FPS escolhido (o menu mostra essa taxa), e o valor aparece no rodapé.
  Valores altos pesam mais; acima de x8 o menu avisa. Com a interpolação desligada a
  captura volta à taxa cheia.
- **Botão Configurações**: abre um diálogo para trocar a tecla de cada atalho global
  (parar o overlay, contador de FPS e FSR/nitidez), escolher se o contador de FPS
  aparece ao iniciar, abrir a pasta das preferências e restaurar os padrões. Teclas
  repetidas são recusadas com um aviso, e **Cancelar**/**Esc** descarta as mudanças.
- As alterações são salvas automaticamente após uma breve pausa nos ajustes.
- **Iniciar overlay**, **Sair** e o botão de fechar a janela salvam imediatamente,
  sem precisar de um botão de confirmação.
- Ao voltar ao menu (atalho de parada) ou reabrir o app, são restaurados o tipo de
  fonte, backend, FPS, escala, algoritmo, nitidez, multiplicador da geração de
  quadros, motor, Ultra Smooth, modo de desempenho, baixa latência, atalhos, idioma
  e a preferência do contador de FPS.
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

## Idioma da interface

O app fala **inglês (padrão na primeira execução)**, **português do Brasil** e
**chinês simplificado**. A troca é feita em **Configurações → PREFERÊNCIAS → Idioma**
e vale imediatamente após salvar: o menu, o diálogo, o painel do overlay, as
mensagens de erro e até a tela de abertura passam a usar o idioma escolhido. A
escolha fica gravada junto das outras preferências (`language` no `settings.json`).

## Tela de abertura (splash)

Ao iniciar, aparece uma janela sem bordas, na mesma cor de fundo do app, com o logo,
o nome **Free Lossless** e a assinatura *"Mais fluidez. Sem modificar seu jogo."* Ela
fica visível por alguns segundos enquanto o OpenCV, o NumPy, o Pygame e o DXCAM são
carregados — no executável isso leva segundos — e se fecha sozinha assim que o menu
está pronto. A janela não bloqueia nada: o carregamento acontece em segundo plano e a
barra de progresso continua animada mesmo em máquinas lentas (uma dica aparece se
demorar mais que o normal).

## Desempenho do overlay

O gargalo do overlay era o pós-processamento na resolução cheia do monitor, a cada
frame, além de cópias desnecessárias na captura:

Medições na resolução interna (800 × 600; no modo de desempenho, 1280 × 720),
numa máquina de teste modesta com 2 núcleos — em um PC comum os números são bem
menores:

| Etapa | Antes (1080p) | Agora (resolução interna) |
| --- | --- | --- |
| CAS / nitidez adaptativa | ~95 ms | ~2,6 ms (800 × 600) · ~12 ms (1280 × 720) |
| Caminho FSR completo | ~127 ms | ~5 ms (800 × 600) · ~15 ms (1280 × 720) |
| Nitidez simples | ~11 ms | ~3 a 5 ms |
| Conversão BGRA→RGB (BitBlt) | ~11 ms | ~0,3 ms (`cv2.cvtColor`) |
| Upscale Lanczos | ~22 ms | bicúbico, ~2 ms |

Além disso:

- A nitidez e o CAS acontecem **antes** do upscale, na resolução interna (800×600 ou
  1280×720 no modo de desempenho). Fazer o mesmo trabalho na resolução da tela custa
  10 a 20 vezes mais por frame.
- As filas descartam o frame **mais antigo** quando enchem, em vez de travar a
  captura: o overlay mostra sempre o frame mais recente disponível.
- Se a pipeline atrasar (por exemplo, um multiplicador alto numa GPU fraca), o painel
  passa a exibir a captura direta e marca `LIVE` em vez de congelar na imagem antiga.
- O contador de FPS é medido de verdade, numa janela de meio segundo: se a pipeline
  não acompanhar, o número cai em vez de mentir.
- O processo do overlay roda com prioridade alta, e o worker de interpolação também.

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
