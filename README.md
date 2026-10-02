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

## Funcionam juntos?

| Recurso | Onde roda | Precisa de D3D11? |
| --- | --- | --- |
| Interpolação de quadros (RIFE / DIS) | overlay | não |
| Filtros internos (nitidez, vibrance, claridade) | overlay | não |
| ReShade (qualquer efeito, inclusive LUTs) | overlay, via hook D3D11 | sim |
| ReShade no jogo (antes da captura) | jogo | não |

## Build em pasta (abre bem mais rápido)

O artifact do CI traz **duas versões**:

- `FreeLossless-Windows-x64` — o `.exe` único, prático de copiar.
- `FreeLossless-Windows-x64-portable` — a versão em pasta (`FreeLossless/FreeLossless.exe`
  ao lado das DLLs). **Use esta no dia a dia**: um `.exe` único de ~260 MB se
  descompacta toda vez que abre, o que adiciona segundos ao boot.

Para gerar localmente: `python build_app.py onefile`, `python build_app.py onedir` ou
`python build_app.py both`.

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

Medições na resolução interna, numa máquina de teste modesta com 2 núcleos — em um PC
comum os números são bem menores:

| Etapa | Antes (1080p) | Agora (resolução interna) |
| --- | --- | --- |
| CAS / nitidez adaptativa | ~95 ms | ~2,6 ms (800 × 600) · ~12 ms (1280 × 720) |
| Caminho FSR completo | ~127 ms | ~5 ms (800 × 600) · ~15 ms (1280 × 720) |
| Nitidez simples | ~11 ms | ~3 a 5 ms |
| Conversão BGRA→RGB (BitBlt) | ~11 ms | ~0,3 ms (`cv2.cvtColor`) |
| Upscale Lanczos | ~22 ms | bicúbico, ~2 ms |

## FPS de saída: fixo ou ilimitado

Por padrão a saída é fixa (30 a 120 FPS no menu) e a captura é agendada a partir
dela: **FPS ÷ multiplicador**. Em x2 a 120 FPS, o jogo é capturado a 60 FPS e os 60
frames que faltam são interpolados — o overlay entrega exatamente 120 por segundo.

O botão **Ilimitado (sem vsync)**, ao lado dos presets de FPS, tira esse teto:

- **Saída sem ritmo**: cada quadro pronto é apresentado na hora, sem esperar intervalo
  nenhum (o overlay já não usa vsync — nem no caminho SDL/D3D11 — então nada mais
  segura a apresentação).
- **Captura sem agendamento**: a captura deixa de ser "1 a cada 16 ms" e passa a pegar
  **todo quadro novo que o jogo produz**, no ritmo real dele. Em x2, cada quadro
  capturado continua rendendo um interpolado — 60 FPS de jogo viram 120 na tela, e um
  jogo a 144 FPS vira 288.
- **Nada de repetir à toa**: com teto, repetir a imagem segurada é inofensivo (o overlay
  apresenta no relógio); sem teto, a mesma imagem não é apresentada duas vezes — ela só
  inflaria o contador e queimaria CPU.
- O limite de geração do worker passa a ser o intervalo real entre capturas, então um
  motor que não acompanha simplesmente não gera os extras (a imagem continua no ritmo do
  jogo, nunca um slideshow) — e, se o **Auto** estiver ligado, a resolução interna desce
  um degrau para o gerador dar conta.

Quando o modo ilimitado está ligado, o slider de FPS e os presets ficam desabilitados
(não têm efeito) e o resumo do rodapé passa a mostrar `FPS ilimitado`.

### Resolução interna

A resolução em que a pipeline trabalha é escolhida em **Configurações → FILTROS →
Resolução interna**, com **Auto** como padrão:

| Escolha | O que faz |
| --- | --- |
| **Auto** (padrão) | Processa no tamanho da fonte, então um jogo em 1080p em tela cheia **não** é reduzido para depois ser ampliado — a imagem sai nítida, sem o aspecto de "144p". Com o upscale neural, usa metade da tela, porque o modelo dobra o quadro. |
| **Desempenho (800 × 600)** / **HD (1280 × 720)** / **Full HD (1920 × 1080)** | Força um alvo fixo, sempre encaixado dentro do tamanho da fonte (nunca distorce e nunca amplia duas vezes). |
| **Nativa** | Igual ao tamanho da fonte. |

O alvo é sempre encaixado **preservando o formato** da fonte: um jogo 4:3 continua 4:3,
mesmo que o alvo seja 16:9.

O interpolador custa tempo em proporção aos pixels que vê. Medições nesta máquina de
2 núcleos (motor rápido DIS):

| Resolução processada | Custo por quadro gerado | Teto de geração |
| --- | --- | --- |
| 800 × 600 | ~19 ms | ~54 quadros/s |
| 1280 × 720 | ~48 ms | ~21 quadros/s |
| 1920 × 1080 | ~83 ms | ~12 quadros/s |

Por isso o **Auto** também se adapta: se, numa janela de 3 segundos, a taxa de frames
gerados que chega à tela fica abaixo de 75% do que o multiplicador pede (por exemplo,
60/s num 2x a 120 FPS), ele desce um degrau (1,0 → 0,7 → 0,49 → 0,34 do alvo) e continua
medindo. É uma decisão por janela, no começo da sessão, e o motivo vai para o log
(`[imagem] geração 12/60 quadros/s: resolução interna reduzida para 1344x756`) — melhor
uma imagem um pouco mais suave do que um overlay travado. Quem escolhe uma resolução no
menu nunca sofre adaptação.

Além disso:

- A nitidez e o CAS acontecem **antes** do upscale, na resolução interna. Fazer o
  mesmo trabalho na resolução da tela custa 10 a 20 vezes mais por frame.
- As filas descartam o frame **mais antigo** quando enchem, em vez de travar a
  captura: o overlay mostra sempre o frame mais recente disponível.
- A geração de frames é **adaptativa**: o worker só interpola o que cabe no intervalo
  entre duas capturas. Um motor mais lento que a captura deixa de enfileirar frames
  atrasados — melhor mostrar só os frames reais, sempre novos, do que um slideshow de
  frames interpolados velhos.
- A imagem **nunca para**: quando não há frame gerado pronto, o overlay repete a última
  imagem exibida. Um atraso curto (menos de meio segundo) não muda nada na tela; um
  atraso longo entra em **LIVE** — e o overlay fica na captura pelo episódio inteiro, só
  voltando para `FG` depois de meio segundo de frames gerados. Não existe mais a troca
  de fonte a cada quadro, que era o flicker visível.
- As **imagens ao vivo** (modo LIVE) passam pelo mesmo caminho de renderização dos
  frames gerados: mesma nitidez, mesmo upscale, mesmo custo. Antes elas usavam um
  caminho barato, e a diferença de nitidez entre `FG` e `LIVE` aparecia como cintilação
  nos textos e nas bordas.
- O worker de pós-processamento **espera na fila** em vez de fazer polling a cada 20 ms,
  e a captura dorme até o próximo quadro em vez de acordar a cada 1 ms.
- O chip de status não pisca: ele só marca `LIVE` depois de um atraso contínuo de
  meio segundo e só volta para `FG` depois de outro meio segundo de frames gerados — e
  enquanto isso a imagem continua na captura, sem alternar. O chip também mostra a taxa
  real de geração (por exemplo, `FG 118/s`).
- Com **Ilimitado (sem vsync)** ligado, não há agendamento nenhum: a captura roda a cada
  quadro novo do jogo e a apresentação acontece assim que um quadro fica pronto.
- O contador de FPS é medido de verdade, numa janela de meio segundo: se a pipeline
  não acompanhar, o número cai em vez de mentir.
- O processo do overlay roda com prioridade alta; o worker de interpolação roda com
  prioridade **abaixo do normal**, para nunca competir com o jogo nem com a exibição.
- Os filtros externos (nitidez/upscale) têm um **interruptor próprio** no menu, como a
  interpolação de quadros: desligado, os frames vão para a tela sem nitidez, sem FSR e
  sem upscale por IA, só com um redimensionamento simples — e o modelo de IA nem é
  carregado.
- Motor de IA sem GPU (RIFE na CPU) leva segundos por frame: o worker detecta e troca
  para o motor rápido (DIS Flow) na mesma sessão, em vez de travar o overlay.
- Com DirectML o RIFE roda na GPU: escolha **AI (RIFE ONNX)** para a melhor qualidade de
  interpolação; o motor **Fast (DIS Flow)** continua sendo o mais leve.

### Filtros de IA no Windows (RIFE e AI SuperRes)

Os dois filtros de IA rodam em ONNX Runtime. No Windows o app instala o
`onnxruntime-directml`, então **os modelos rodam na GPU de qualquer fabricante**
(NVIDIA, AMD ou Intel) — a RTX 2060, por exemplo, usa DirectML normalmente. Sem
DirectML/CUDA o ONNX Runtime cai para a CPU, onde o RIFE leva segundos por quadro e o
upscale de IA leva centenas de milissegundos; para o overlay nunca virar um slideshow:

- **Motor de interpolação**: se o motor de IA não conseguir iniciar ou levar mais de
  250 ms por quadro, o worker troca para o motor rápido (**Fast (DIS Flow)**) na mesma
  sessão e registra o motivo no log.
- **AI SuperRes**: o custo do filtro é medido uma vez, na abertura do overlay. Se não
  couber no orçamento de quadros (2 intervalos de quadro), o filtro é desligado naquela
  sessão, com o motivo no log e no console. Filtro lento não derruba mais o FPS.
- O modelo que acompanha o app é um **FSRCNN x2 de verdade** (`models/fsrcnn_x2.onnx`,
  100 KB, MIT) — veja `models/README.md`. O arquivo anterior no repositório era um
  placeholder inválido, então o filtro não fazia nada.
- A conversão **YCbCr** usada no treino do modelo está embutida no grafo ONNX: o app
  entrega RGB e a conversão roda na GPU, sem custo na CPU.

## ReShade rodando no overlay (modo D3D11)

O ReShade **pode** ser injetado no overlay — é a mesma técnica do Magpie e do Lossless
Scaling: o app passa a apresentar a imagem por **Direct3D 11** em vez de GDI, e o
ReShade instalado na pasta do app hooka esse processo normalmente. Em **RESHADE (D3D11)**
no menu:

1. **Como o overlay desenha → D3D11 (permite o ReShade hookar o overlay)**. A janela
   continua sendo a mesma (click-through, sempre no topo, fora das capturas); só a
   apresentação muda. Se a máquina recusar D3D11, o overlay **cai sozinho para GDI** e
   registra o motivo no log — ele nunca deixa de abrir.
2. **Baixar instalador do ReShade** — o app baixa o instalador oficial (resolve a versão
   atual na página do ReShade; a lista de downloads só mantém a última versão, então
   fixar uma URL quebraria a cada lançamento) e mostra onde ele está.
3. Execute o instalador e escolha **FreeLossless.exe** na lista. O status no menu passa a
   mostrar `ReShade encontrado na pasta do app (dxgi.dll, ReShade.ini): seus efeitos valem
   para a imagem do overlay`.

Com isso, os efeitos do ReShade (LumaSharpen, Vibrance, LUTs, grão, bloom…) rodam **na
imagem do overlay**, em qualquer jogo — porque o jogo nunca é tocado: o overlay só
mostra a imagem que já captura. ReShade não é redistribuído junto com o app; o download
usa a página oficial.

Os filtros internos de **FILTROS EXTERNOS** continuam disponíveis e não precisam de
ReShade (nem de D3D11).

## Filtros externos (estilo ReShade)

O ReShade se instala **dentro do jogo** (ele se injeta no executável para hookar o
DirectX), então não existe como "instalar o ReShade no app": quem precisa do ReShade é
o jogo, e é justamente isso que anti-cheats bloqueiam. O overlay, por outro lado, é uma
janela separada que captura a imagem final do jogo — então ele aplica os filtros na
imagem que já é dele, sem tocar no jogo. Resultado: filtros funcionam em **qualquer**
jogo, com ou sem anti-cheat, em janela ou tela cheia.

Presets (menu → **FILTROS EXTERNOS**), aplicados na resolução interna antes do upscale:

| Preset | Efeitos (equivalentes do ReShade) |
| --- | --- |
| Desligado | nada |
| Suave | LumaSharpen (clamp 16) + Vibrance |
| Nítido | LumaSharpen (clamp 24) + Clarity |
| Vívido | Vibrance + Contraste (curva S) |

- **LumaSharpen**: nitidez só onde há detalhe de luma, com *clamp* para não criar halos.
- **Vibrance**: aumenta a saturação das cores apagadas e preserva as já saturadas.
- **Clarity**: contraste local de raio largo.
- **Contraste**: curva S suave por tabela de consulta (preto e branco fixos).

Além disso, quando o jogo selecionado já tem ReShade instalado, o menu mostra
`ReShade encontrado neste jogo (...)` — útil para não duplicar o mesmo look: como
capturamos a imagem final, os efeitos do ReShade já aparecem no overlay.

Custo medido nesta máquina de teste (2 núcleos, 800 × 600): Desligado 0 ms · Nítido
~7 ms · Vívido ~6 ms · Suave ~10 ms por quadro. O custo do preset escolhido é medido e
registrado no log na abertura do overlay, com aviso quando passa de um intervalo de
quadro.

## Janela do overlay (click-through)

O overlay fica sempre no topo, **sem receber cliques** (`WS_EX_TRANSPARENT`) e
**sem roubar foco** (`WS_EX_NOACTIVATE`), além de excluído de capturas de tela
(`WDA_EXCLUDEFROMCAPTURE`). O Windows reaplica estilos quando a janela é recriada e
pode devolver o foco ao overlay depois da tecla Windows ou de um Alt+Tab — por isso os
estilos são reafirmados a cada mudança de geometria e a cada meio segundo, o que
resolve o caso em que o overlay "saía" e dava para arrastá-lo.

### Diagnóstico

Cada sessão do overlay grava um resumo em `overlay.log`, na mesma pasta do arquivo de
preferências (`%LOCALAPPDATA%\FreeLossless` no Windows). O log registra resolução
interna, FPS exibidos, frames gerados por segundo, fila e cada troca de fonte.

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
