"""Tests for model selection defaults."""

import importlib
import os
import unittest
from unittest.mock import patch


class DefaultModelSelectionTest(unittest.TestCase):
    def test_default_model_is_free(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TESTGEN_MODEL", None)
            os.environ.pop("TESTGEN_MODELS", None)
            from testgen import nodes
            importlib.reload(nodes)
            self.assertEqual(
                nodes.MODELS,
                [
                    "google/gemma-4-31b-it:free",
                    "google/gemma-4-26b-a4b-it:free",
                    "qwen/qwen3.8-27b:free",
                    "cohere/north-mini-code:free",
                ],
            )
