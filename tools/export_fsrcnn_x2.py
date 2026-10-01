"""Rebuild ``models/fsrcnn_x2.onnx`` from the FSRCNN x2 checkpoint.

The AI upscaling filter needs a small super-resolution network that can run in
real time on a GPU. The repository shipped a placeholder file that no runtime
could load, so the filter silently did nothing.

This script converts a trained checkpoint into ONNX **without requiring
PyTorch**: the ``.pt`` file is a zip archive with the tensors stored as raw
float32, so it can be read directly and the graph is built with the ``onnx``
package.

Weights: ``FSRCNN-x2.pt`` from https://github.com/Nhat-Thanh/FSRCNN-Pytorch
(MIT License, Copyright (c) 2022 VuNguyenNhatThanh). Architecture from the same
repository (``neuralnet.py``): 5x5 feature extraction, 1x1 shrink, four 3x3
mapping layers, 1x1 expand and a 9x9 transposed convolution with stride 2.

Usage:
    python tools/export_fsrcnn_x2.py --checkpoint /path/to/FSRCNN-x2.pt \\
        --output models/fsrcnn_x2.onnx
    python tools/export_fsrcnn_x2.py --checkpoint ... --check tests/data/lr.png \\
        --reference tests/data/hr.png

Needs ``pip install onnx numpy``; ``onnxruntime`` is used for the optional
checks (shapes and the PSNR comparison against bicubic).
"""
import argparse
import pickle
import zipfile
from pathlib import Path

import numpy as np

STORAGE_DTYPES = {
    "FloatStorage": np.float32,
    "DoubleStorage": np.float64,
    "LongStorage": np.int64,
    "IntStorage": np.int32,
    "HalfStorage": np.float16,
}


class _Storage:
    """Stand-in for the torch storage objects referenced by the checkpoint."""

    def __init__(self, kind, key, location=None, numel=None):
        self.kind = kind
        self.key = str(key)
        self.dtype = STORAGE_DTYPES.get(kind, np.float32)
        self.location = location
        self.numel = numel


class _TorchStub:
    """Any torch class the pickle stream mentions, used only for its name."""

    def __init__(self, name):
        self.__name__ = name

    def __call__(self, *args, **kwargs):
        key = args[1] if len(args) > 1 else (args[0] if args else "?")
        return _Storage(self.__name__, key, *args[2:])


def load_checkpoint(path):
    """Read a ``torch.save`` state dict as ``{name: np.ndarray}``."""
    archive = zipfile.ZipFile(path)
    prefix = next(name.rsplit("/", 1)[0] for name in archive.namelist() if name.endswith("data.pkl"))

    def rebuild_tensor_v2(storage, storage_offset, size, stride, requires_grad=None, backward_hooks=None):
        values = np.frombuffer(archive.read(f"{prefix}/data/{storage.key}"), dtype=storage.dtype)
        offset = int(storage_offset or 0)
        count = int(np.prod(size)) if size else int(values.size)
        return values[offset:offset + count].reshape(size).copy()

    class Unpickler(pickle.Unpickler):
        def persistent_load(self, pid):                     # torch legacy storage ids
            _kind, storage_type, key, location, numel = pid
            return _Storage(getattr(storage_type, "__name__", str(storage_type)), key, location, numel)

        def find_class(self, module, name):
            if module == "torch._utils" and name == "_rebuild_tensor_v2":
                return rebuild_tensor_v2
            if module.startswith("torch"):
                return _TorchStub(name)
            return super().find_class(module, name)

    with archive.open(f"{prefix}/data.pkl") as stream:
        state = Unpickler(stream).load()
    return {key: value for key, value in state.items() if isinstance(value, np.ndarray)}


# The checkpoint was trained on YCbCr (see utils/common.py in the source repository):
# Y = 0.299R + 0.587G + 0.114B clipped to [16, 235], Cb/Cr clipped to [16, 240],
# then divided by 255. The graph below does that conversion and its inverse itself,
# so the app can keep feeding plain RGB frames and the colour handling still matches
# the training pipeline (and runs on the GPU, not on the CPU).
FORWARD_MATRIX = {
    "Y": (0.299, 0.587, 0.114, 0.0, 16.0, 235.0),
    "Cb": (-0.16874, -0.33126, 0.5, 128.0, 16.0, 240.0),
    "Cr": (0.5, -0.41869, -0.08131, 128.0, 16.0, 240.0),
}
INVERSE_MATRIX = {                     # Y + a * Cr + b * Cb + offset, clipped to [0, 255]
    "R": (1.402, 0.0, -179.456),
    "G": (-0.71414, -0.34414, 135.45984),
    "B": (0.0, 1.772, -226.816),
}


def build_onnx(state):
    """Assemble the FSRCNN x2 graph with the trained weights as initializers."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    nodes, initializers = [], []

    def tensor(name, value):
        array = np.asarray(value, dtype=np.float32)
        initializers.append(numpy_helper.from_array(array, name))
        return name

    def integer_tensor(name, value):
        initializers.append(numpy_helper.from_array(np.asarray(value, dtype=np.int64), name))
        return name

    channels = integer_tensor("split.channels", [1, 1, 1])
    scale = tensor("color.scale255", 255.0)

    def split(data, outputs):
        nodes.append(helper.make_node("Split", [data, channels], outputs, axis=1))
        return outputs

    def linear(tag, terms, offset, low, high):
        """Sum(weight * term) + offset, clipped between low and high."""
        products = []
        for index, (source, coefficient) in enumerate(terms):
            if not coefficient:
                continue
            name = tensor(f"{tag}.w{index}", coefficient)
            nodes.append(helper.make_node("Mul", [source, name], [f"{tag}.t{index}"]))
            products.append(f"{tag}.t{index}")
        summed = products[0] if len(products) == 1 else f"{tag}.sum"
        if len(products) > 1:
            nodes.append(helper.make_node("Sum", products, [summed]))
        nodes.append(helper.make_node("Add", [summed, tensor(f"{tag}.offset", offset)], [f"{tag}.shift"]))
        nodes.append(helper.make_node("Clip", [f"{tag}.shift", tensor(f"{tag}.low", low),
                                               tensor(f"{tag}.high", high)], [f"{tag}.out"]))
        return f"{tag}.out"

    # --- RGB [0,1] -> YCbCr (training space) -----------------------------------
    nodes.append(helper.make_node("Mul", ["input", scale], ["rgb.255"]))
    red, green, blue = split("rgb.255", ["rgb.r", "rgb.g", "rgb.b"])
    components = {"R": red, "G": green, "B": blue}
    ycc = {}
    for channel, values in FORWARD_MATRIX.items():
        red_weight, green_weight, blue_weight, offset, low, high = values
        terms = [(components[letter], coefficient)
                 for letter, coefficient in zip("RGB", (red_weight, green_weight, blue_weight))]
        ycc[channel] = linear(f"ycc.{channel}", terms, offset, low, high)
    nodes.append(helper.make_node("Concat", [ycc["Y"], ycc["Cb"], ycc["Cr"]], ["ycc.255"], axis=1))
    nodes.append(helper.make_node("Div", ["ycc.255", scale], ["ycc.unit"]))

    # --- the network ------------------------------------------------------------
    previous = "ycc.unit"

    def conv(name, kernel, stride=1, pads=None):
        nonlocal previous
        pads = pads if pads is not None else (kernel // 2,) * 2
        nodes.append(helper.make_node(
            "Conv", [previous, tensor(f"{name}.w", state[f"{name}.weight"]),
                     tensor(f"{name}.b", state[f"{name}.bias"])], [f"{name}.out"],
            kernel_shape=(kernel, kernel), pads=(pads[0], pads[1], pads[0], pads[1]),
            strides=(stride, stride), group=1))
        previous = f"{name}.out"

    def prelu(name):
        nonlocal previous
        slope = np.asarray(state[f"{name}.weight"], dtype=np.float32).reshape(-1, 1, 1)
        nodes.append(helper.make_node("PRelu", [previous, tensor(f"{name}.slope", slope)], [f"{name}.out"]))
        previous = f"{name}.out"

    conv("feature_extract", 5)
    prelu("activation_1")
    conv("shrink", 1)
    prelu("activation_2")
    for index in (1, 2, 3, 4):
        conv(f"map_{index}", 3)
    prelu("activation_3")
    conv("expand", 1)
    prelu("activation_4")

    # Deconvolution: 9x9, stride 2, padding 4 and output_padding 1 -> exactly 2x.
    nodes.append(helper.make_node(
        "ConvTranspose", [previous, tensor("deconv.w", state["deconv.weight"]),
                          tensor("deconv.b", state["deconv.bias"])], ["deconv.out"],
        kernel_shape=(9, 9), pads=(4, 4, 4, 4), strides=(2, 2), output_padding=(1, 1), group=1))
    nodes.append(helper.make_node("Clip", ["deconv.out", tensor("clip.low", 0.0),
                                           tensor("clip.high", 1.0)], ["ycc.prediction"]))

    # --- YCbCr -> RGB -----------------------------------------------------------
    nodes.append(helper.make_node("Mul", ["ycc.prediction", scale], ["ycc.prediction.255"]))
    luma, blue_chroma, red_chroma = split("ycc.prediction.255", ["out.Y", "out.Cb", "out.Cr"])
    chroma = {"Cb": blue_chroma, "Cr": red_chroma}
    restored = []
    for channel, (cr_weight, cb_weight, offset) in INVERSE_MATRIX.items():
        terms = [(luma, 1.0), (chroma["Cr"], cr_weight), (chroma["Cb"], cb_weight)]
        restored.append(linear(f"rgb.{channel}", terms, offset, 0.0, 255.0))
    nodes.append(helper.make_node("Concat", restored, ["rgb.out.255"], axis=1))
    nodes.append(helper.make_node("Div", ["rgb.out.255", scale], ["output"]))

    graph = helper.make_graph(
        nodes, "fsrcnn_x2",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, None, None])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, None, None])],
        initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    # Keep the IR version inside what onnxruntime accepts (the onnx package writes
    # 14 by default, which older runtimes refuse to load).
    model.ir_version = 8
    model.doc_string = ("FSRCNN x2 (MIT, VuNguyenNhatThanh/FSRCNN-Pytorch) with the YCbCr "
                        "conversion from its training pipeline, built by tools/export_fsrcnn_x2.py")
    onnx.checker.check_model(model)
    return model


def to_ycbcr(rgb):
    """The YCbCr conversion from the checkpoint's training pipeline (video range)."""
    values = np.asarray(rgb, dtype=np.float32)
    red, green, blue = values[..., 0], values[..., 1], values[..., 2]
    y = 0.299 * red + 0.587 * green + 0.114 * blue
    cb = -0.16874 * red - 0.33126 * green + 0.5 * blue + 128.0
    cr = 0.5 * red - 0.41869 * green - 0.08131 * blue + 128.0
    return np.stack([np.clip(y, 16, 235), np.clip(cb, 16, 240), np.clip(cr, 16, 240)], axis=-1)


def psnr(first, second, max_value=255.0):
    first = np.asarray(first, dtype=np.float32)
    second = np.asarray(second, dtype=np.float32)
    if first.shape != second.shape:
        raise ValueError(f"shape mismatch: {first.shape} vs {second.shape}")
    mse = float(np.mean((first - second) ** 2))
    return float("inf") if mse == 0 else 10.0 * np.log10(max_value ** 2 / mse)


def check_model(path, lr_path=None, reference_path=None):
    """Compare the export with the checkpoint: shapes, dynamic size and quality."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    results = {}

    for height, width in ((64, 64), (100, 160)):
        sample = np.random.default_rng(7).random((1, 3, height, width), dtype=np.float32)
        output = session.run(None, {"input": sample})[0]
        expected = (1, 3, height * 2, width * 2)
        assert output.shape == expected, f"{output.shape} != {expected}"
        assert 0.0 <= output.min() and output.max() <= 1.0001, (output.min(), output.max())
    results["shapes"] = "ok (64x64 -> 128x128 and 100x160 -> 200x320)"

    if lr_path and reference_path:
        import cv2

        lr = cv2.cvtColor(cv2.imread(str(lr_path)), cv2.COLOR_BGR2RGB)
        reference = cv2.cvtColor(cv2.imread(str(reference_path)), cv2.COLOR_BGR2RGB)
        hr = reference
        # Same degradation and same measurement space as test.py in the source
        # repository: blurred input, PSNR on the YCbCr channels normalised to [0, 1].
        degraded = cv2.GaussianBlur(lr.astype(np.float32), (0, 0), 0.3)
        prepared = np.transpose(degraded / 255.0, (2, 0, 1))[np.newaxis, ...]
        out = session.run(None, {"input": prepared})[0]
        ai = np.clip(np.transpose(out[0], (1, 2, 0)), 0, 1) * 255.0
        bicubic = cv2.resize(degraded, (hr.shape[1], hr.shape[0]), interpolation=cv2.INTER_CUBIC)
        target = to_ycbcr(hr) / 255.0
        results["ai_psnr_ycbcr"] = round(psnr(to_ycbcr(ai) / 255.0, target, max_value=1.0), 2)
        results["bicubic_psnr_ycbcr"] = round(psnr(to_ycbcr(bicubic) / 255.0, target, max_value=1.0), 2)
        results["ai_better"] = results["ai_psnr_ycbcr"] > results["bicubic_psnr_ycbcr"]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="FSRCNN-x2.pt from Nhat-Thanh/FSRCNN-Pytorch")
    parser.add_argument("--output", default="models/fsrcnn_x2.onnx")
    parser.add_argument("--check", action="store_true", help="validate the written model with onnxruntime")
    parser.add_argument("--lr", help="low resolution image used for the quality check")
    parser.add_argument("--reference", help="high resolution image used for the quality check")
    args = parser.parse_args()

    state = load_checkpoint(args.checkpoint)
    required = {"feature_extract.weight", "shrink.weight", "map_1.weight", "map_4.weight",
                "expand.weight", "deconv.weight", "deconv.bias"}
    missing = required - set(state)
    if missing:
        raise SystemExit(f"checkpoint is not an FSRCNN x2 state dict, missing: {sorted(missing)}")

    model = build_onnx(state)
    import onnx

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, output)
    print(f"{output} escrito ({output.stat().st_size} bytes)")

    if args.check or args.lr:
        for key, value in check_model(output, args.lr, args.reference).items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
