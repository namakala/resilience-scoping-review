"""Tests for config/settings.py — env var loading, defaults, validation."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from utils.exceptions import ConfigurationError  # noqa: E402


class TestGroqApiKey(unittest.TestCase):
    """Tests for groq_api_key() — required setting."""

    def test_missing_raises_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import groq_api_key as f

            with self.assertRaises(ConfigurationError):
                f()

    def test_set_returns_value(self):
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "sk-test123"}):
            from config.settings import groq_api_key as f

            self.assertEqual(f(), "sk-test123")


class TestGroqModel(unittest.TestCase):
    """Tests for groq_model() — optional with fallback chain."""

    def test_default_when_unset(self):
        with mock.patch.dict(
            "os.environ",
            {},
            clear=True,
        ):
            from config.settings import groq_model as f

            self.assertEqual(f(), "openai/gpt-oss-120b")

    def test_groq_model_override(self):
        with mock.patch.dict(
            "os.environ",
            {"GROQ_MODEL": "mixtral-8x7b-32768"},
        ):
            from config.settings import groq_model as f

            self.assertEqual(f(), "mixtral-8x7b-32768")

    def test_model_name_fallback(self):
        with mock.patch.dict(
            "os.environ",
            {"MODEL_NAME": "llama-3.3-70b"},
        ):
            from config.settings import groq_model as f

            self.assertEqual(f(), "llama-3.3-70b")

    def test_groq_model_takes_priority(self):
        with mock.patch.dict(
            "os.environ",
            {
                "GROQ_MODEL": "groq-model",
                "MODEL_NAME": "fallback-model",
            },
        ):
            from config.settings import groq_model as f

            self.assertEqual(f(), "groq-model")


class TestGroqTimeout(unittest.TestCase):
    """Tests for groq_timeout() — optional int with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import groq_timeout as f

            self.assertEqual(f(), 60)

    def test_override(self):
        with mock.patch.dict("os.environ", {"GROQ_TIMEOUT": "120"}):
            from config.settings import groq_timeout as f

            self.assertEqual(f(), 120)

    def test_invalid_raises_error(self):
        with mock.patch.dict("os.environ", {"GROQ_TIMEOUT": "not-a-number"}):
            from config.settings import groq_timeout as f

            with self.assertRaises(ConfigurationError):
                f()


class TestGroqMaxRetries(unittest.TestCase):
    """Tests for groq_max_retries() — optional int with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import groq_max_retries as f

            self.assertEqual(f(), 2)

    def test_override(self):
        with mock.patch.dict("os.environ", {"GROQ_MAX_RETRIES": "5"}):
            from config.settings import groq_max_retries as f

            self.assertEqual(f(), 5)


class TestBatchSize(unittest.TestCase):
    """Tests for batch_size() — optional int with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import batch_size as f

            self.assertEqual(f(), 15)

    def test_override(self):
        with mock.patch.dict("os.environ", {"BATCH_SIZE": "30"}):
            from config.settings import batch_size as f

            self.assertEqual(f(), 30)


class TestEmbeddingModel(unittest.TestCase):
    """Tests for embedding_model() — optional str with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import embedding_model as f

            self.assertEqual(f(), "all-MiniLM-L6-v2")

    def test_override(self):
        with mock.patch.dict("os.environ", {"EMBEDDING_MODEL": "custom-model"}):
            from config.settings import embedding_model as f

            self.assertEqual(f(), "custom-model")


class TestModelCacheDir(unittest.TestCase):
    """Tests for model_cache_dir() — optional Path with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import model_cache_dir as f

            result = f()
            expected = Path("~/.cache/huggingface/hub").expanduser()
            self.assertEqual(result, expected)
            self.assertIsInstance(result, Path)

    def test_override(self):
        with mock.patch.dict(
            "os.environ",
            {"MODEL_CACHE_DIR": "/custom/cache"},
        ):
            from config.settings import model_cache_dir as f

            self.assertEqual(f(), Path("/custom/cache"))


class TestLogLevel(unittest.TestCase):
    """Tests for log_level() — optional str with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import log_level as f

            self.assertEqual(f(), "INFO")

    def test_override(self):
        with mock.patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}):
            from config.settings import log_level as f

            self.assertEqual(f(), "DEBUG")


class TestPathSettings(unittest.TestCase):
    """Tests for path settings — optional Path with defaults."""

    def test_data_path_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import data_path as f

            self.assertEqual(f(), Path("data/raw/data.csv"))

    def test_tags_path_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import tags_path as f

            self.assertEqual(f(), Path("data/raw/tags.csv"))

    def test_processed_data_path_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import processed_data_path as f

            self.assertEqual(f(), Path("data/processed"))

    def test_data_path_override(self):
        with mock.patch.dict("os.environ", {"DATA_PATH": "/custom/data.csv"}):
            from config.settings import data_path as f

            self.assertEqual(f(), Path("/custom/data.csv"))


class TestBm25TokenizerConfig(unittest.TestCase):
    """Tests for bm25_tokenizer_config() — optional str with default."""

    def test_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            from config.settings import bm25_tokenizer_config as f

            self.assertEqual(f(), "lowercase,split_by_space")

    def test_override(self):
        with mock.patch.dict(
            "os.environ",
            {"BM25_TOKENIZER_CONFIG": "lowercase,split_by_space,remove_stopword"},
        ):
            from config.settings import bm25_tokenizer_config as f

            self.assertEqual(f(), "lowercase,split_by_space,remove_stopword")


if __name__ == "__main__":
    unittest.main()
