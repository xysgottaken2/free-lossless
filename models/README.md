# Modelos

| Arquivo | Para que serve | Origem |
| --- | --- | --- |
| `rife_v4_lite.onnx` | interpolação de quadros do motor **AI (RIFE ONNX)** | modelo RIFE v4 lite do projeto original |
| `fsrcnn_x2.onnx` | filtro **NVIDIA AI SuperRes** (upscale x2 aprendido) | FSRCNN x2 treinado, convertido para ONNX (veja abaixo) |

## fsrcnn_x2.onnx

O filtro AI SuperRes precisava de um modelo de super-resolução; o arquivo que vinha
no repositório era um placeholder inválido (nenhum runtime conseguia carregar), então
o filtro não fazia nada. O arquivo atual é um **FSRCNN x2** de verdade:

- Pesos: [`FSRCNN-x2.pt`](https://github.com/Nhat-Thanh/FSRCNN-Pytorch) — **MIT License**,
  Copyright (c) 2022 VuNguyenNhatThanh. O checkpoint e a arquitetura
  (`neuralnet.py`) vêm desse repositório; o modelo é uma rede de 8 camadas
  (extração 5×5, compressão 1×1, quatro camadas 3×3, expansão 1×1 e uma
  deconvolução 9×9 com stride 2).
- Conversão: `tools/export_fsrcnn_x2.py`, que lê o checkpoint **sem PyTorch** (o
  `.pt` é um zip com os tensores em float32) e monta o grafo ONNX com as mesmas
  contas do treino — incluindo a conversão **YCbCr** que o modelo espera, embutida
  no grafo (a aplicação continua entregando RGB e a conversão roda na GPU).
- Verificação: o script compara o resultado com o bicúbico nas imagens de teste do
  próprio repositório de origem — o FSRCNN x2 ganha em todas (por exemplo, 41,45 dB
  contra 40,64 dB, e 42,40 dB contra 39,87 dB, medidos em YCbCr como no artigo).

Regenerar (precisa apenas de `pip install onnx numpy onnxruntime`):

```bash
python tools/export_fsrcnn_x2.py \
    --checkpoint /caminho/FSRCNN-x2.pt \
    --output models/fsrcnn_x2.onnx --check \
    --lr /caminho/dataset/test/x2/data/img_001_SRF_2_LR.png \
    --reference /caminho/dataset/test/x2/labels/img_001_SRF_2_HR.png
```

## Aviso sobre desempenho

O upscale por IA roda em ONNX Runtime. Com `onnxruntime-directml` (que já vem nas
dependências e no build do Windows) o modelo roda na GPU — alguns milissegundos por
quadro. Sem DirectML/CUDA ele cai para a CPU, onde passa de centenas de milissegundos
por quadro; nesse caso o overlay mede o custo na abertura e **desativa o filtro na
sessão**, registrando o motivo em `overlay.log`, porque um filtro assim derrubaria os
FPS do jogo.
