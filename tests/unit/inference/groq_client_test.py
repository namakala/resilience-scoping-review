"""Tests for inference/groq_client.py — singleton, DI, dry-run."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.groq_client import (  # noqa: E402
    build_messages,
    get_client,
    get_model,
    get_sync_client,
    reset_client,
    set_client,
)
from inference.prompts import PromptBundle  # noqa: E402
from utils.exceptions import ConfigurationError  # noqa: E402


class TestGroqClient(unittest.TestCase):
    """Tests for Groq client singleton and error handling."""

    def setUp(self):
        reset_client()

    def tearDown(self):
        reset_client()

    # -- Missing API key ----------------------------------------------------

    @mock.patch(
        "inference.groq_client.groq_api_key",
        side_effect=ConfigurationError,
    )
    def test_missing_api_key_raises_error(self, mock_key):
        with self.assertRaises(ConfigurationError):
            get_client()

    # -- Client creation (async) --------------------------------------------

    @mock.patch("inference.groq_client.AsyncGroq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_get_client_returns_async_groq(self, mock_key, mock_async_groq):
        client = get_client()
        mock_async_groq.assert_called_once_with(
            api_key="sk-test123",
            timeout=60,
            max_retries=2,
        )
        self.assertIs(client, mock_async_groq.return_value)

    # -- Client creation (sync) ---------------------------------------------

    @mock.patch("inference.groq_client.Groq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_get_sync_client_returns_groq(self, mock_key, mock_groq):
        client = get_sync_client()
        mock_groq.assert_called_once_with(
            api_key="sk-test123",
            timeout=60,
            max_retries=2,
        )
        self.assertIs(client, mock_groq.return_value)

    # -- Async singleton ----------------------------------------------------

    @mock.patch("inference.groq_client.AsyncGroq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_client_singleton(self, mock_key, mock_async_groq):
        c1 = get_client()
        c2 = get_client()
        self.assertIs(c1, c2)
        mock_async_groq.assert_called_once()

    # -- Sync singleton -----------------------------------------------------

    @mock.patch("inference.groq_client.Groq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_sync_client_singleton(self, mock_key, mock_groq):
        c1 = get_sync_client()
        c2 = get_sync_client()
        self.assertIs(c1, c2)
        mock_groq.assert_called_once()

    # -- get_model ----------------------------------------------------------

    def test_get_model_default(self):
        with mock.patch(
            "inference.groq_client.groq_model",
            return_value="openai/gpt-oss-120b",
        ):
            self.assertEqual(get_model(), "openai/gpt-oss-120b")

    def test_get_model_custom(self):
        with mock.patch(
            "inference.groq_client.groq_model",
            return_value="mixtral-8x7b-32768",
        ):
            self.assertEqual(get_model(), "mixtral-8x7b-32768")

    # -- set_client injection -----------------------------------------------

    def test_set_client_injection(self):
        mock_client = mock.MagicMock()
        set_client(mock_client)
        self.assertIs(get_client(), mock_client)

    # -- reset_client -------------------------------------------------------

    @mock.patch("inference.groq_client.AsyncGroq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_reset_client_creates_new_instance(self, mock_key, mock_async_groq):
        mock_async_groq.side_effect = lambda *a, **kw: mock.MagicMock()
        c1 = get_client()
        reset_client()
        c2 = get_client()
        self.assertIsNot(c1, c2)
        self.assertEqual(mock_async_groq.call_count, 2)

    # -- Independent sync/async singletons ----------------------------------

    @mock.patch("inference.groq_client.AsyncGroq")
    @mock.patch("inference.groq_client.Groq")
    @mock.patch("inference.groq_client.groq_api_key", return_value="sk-test123")
    def test_sync_and_async_are_independent(self, mock_key, mock_groq, mock_async_groq):
        async_client = get_client()
        sync_client = get_sync_client()
        self.assertIsNot(async_client, sync_client)


class TestBuildMessages(unittest.TestCase):
    """Tests for build_messages() role-structured array construction."""

    def test_system_and_user(self):
        msgs = build_messages(system="sys", user="usr")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], "sys")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "usr")

    def test_with_fewshot(self):
        msgs = build_messages(
            system="sys",
            user="usr",
            fewshot=[
                {"user": "ex1", "assistant": "resp1"},
                {"user": "ex2", "assistant": "resp2"},
            ],
        )
        self.assertEqual(len(msgs), 6)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")
        self.assertEqual(msgs[1]["content"], "ex1")
        self.assertEqual(msgs[2]["role"], "assistant")
        self.assertEqual(msgs[2]["content"], "resp1")
        self.assertEqual(msgs[3]["role"], "user")
        self.assertEqual(msgs[3]["content"], "ex2")
        self.assertEqual(msgs[4]["role"], "assistant")
        self.assertEqual(msgs[4]["content"], "resp2")
        self.assertEqual(msgs[5]["role"], "user")
        self.assertEqual(msgs[5]["content"], "usr")

    def test_empty_fewshot(self):
        msgs = build_messages(system="sys", user="usr", fewshot=[])
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_from_prompt_bundle(self):
        bundle = PromptBundle(system="sys", user="usr")
        msgs = build_messages(bundle.system, bundle.user)
        self.assertEqual(len(msgs), 2)


if __name__ == "__main__":
    unittest.main()
