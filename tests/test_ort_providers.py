"""The ONNX engines must use the GPU when the runtime offers it.

A filter that quietly runs on the CPU is the difference between a few milliseconds
per frame and hundreds of them, so the provider choice is part of the behaviour.
"""
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

import ort_providers


class ProviderSelectionTests(unittest.TestCase):
    def fake_runtime(self, available, name="onnxruntime"):
        module = ModuleType(name)
        module.get_available_providers = lambda: list(available)
        module.InferenceSession = lambda *args, **kwargs: "session"
        return module

    def test_directml_comes_first(self):
        fake = self.fake_runtime(["CPUExecutionProvider", "DmlExecutionProvider"])
        with patch.dict(sys.modules, {"onnxruntime": fake}):
            self.assertEqual(ort_providers.provider_names(),
                             ["DmlExecutionProvider", "CPUExecutionProvider"])

    def test_cuda_is_the_second_choice(self):
        fake = self.fake_runtime(["CPUExecutionProvider", "CUDAExecutionProvider"])
        with patch.dict(sys.modules, {"onnxruntime": fake}):
            self.assertEqual(ort_providers.provider_names(),
                             ["CUDAExecutionProvider", "CPUExecutionProvider"])

    def test_cpu_is_enough_when_there_is_no_gpu_runtime(self):
        fake = self.fake_runtime(["CPUExecutionProvider"])
        with patch.dict(sys.modules, {"onnxruntime": fake}):
            self.assertEqual(ort_providers.provider_names(), ["CPUExecutionProvider"])

    def test_an_unknown_runtime_still_returns_cpu(self):
        fake = self.fake_runtime(["BizarreExecutionProvider"])
        with patch.dict(sys.modules, {"onnxruntime": fake}):
            self.assertEqual(ort_providers.provider_names(), ["CPUExecutionProvider"])

    def test_gpu_detection(self):
        self.assertTrue(ort_providers.is_gpu(["DmlExecutionProvider", "CPUExecutionProvider"]))
        self.assertTrue(ort_providers.is_gpu(["CUDAExecutionProvider"]))
        self.assertFalse(ort_providers.is_gpu(["CPUExecutionProvider"]))
        self.assertFalse(ort_providers.is_gpu([]))
        self.assertFalse(ort_providers.is_gpu(None))

    def test_describe_never_raises_on_a_broken_session(self):
        class Broken:
            def get_providers(self):
                raise RuntimeError("no session")

        self.assertEqual(ort_providers.describe(Broken()), "?")
        self.assertEqual(ort_providers.describe(None), "?")


if __name__ == "__main__":
    unittest.main()
