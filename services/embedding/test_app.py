import unittest
from unittest.mock import patch
from io import BytesIO

from fastapi import HTTPException

import app


class EmbeddingTests(unittest.TestCase):
    def test_health_and_success_payload(self):
        response = BytesIO(b'{"models":[{"name":"all-minilm:latest"}]}')
        with patch.object(app, "urlopen", return_value=response):
            self.assertEqual(app.health()["model"], app.MODEL_NAME)
        embeddings = BytesIO(b'{"embeddings":[[0.1,0.2],[0.3,0.4]]}')
        with patch.object(app, "urlopen", return_value=embeddings):
            result = app.embeddings(app.EmbeddingRequest(input=["one", "two"]))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][1]["embedding"], [0.3, 0.4])

    def test_rejects_wrong_model(self):
        with self.assertRaises(HTTPException) as rejected:
            app.embeddings(app.EmbeddingRequest(input="text", model="unexpected"))
        self.assertEqual(rejected.exception.status_code, 400)

    def test_rejects_empty_input(self):
        with self.assertRaises(HTTPException) as rejected:
            app.embeddings(app.EmbeddingRequest(input=[]))
        self.assertEqual(rejected.exception.status_code, 400)

    def test_rejects_oversized_batch(self):
        with self.assertRaises(HTTPException) as rejected:
            app.embeddings(app.EmbeddingRequest(input=["x"] * (app.MAX_INPUTS + 1)))
        self.assertEqual(rejected.exception.status_code, 413)

    def test_rejects_oversized_text(self):
        with self.assertRaises(HTTPException) as rejected:
            app.embeddings(app.EmbeddingRequest(input="x" * (app.MAX_CHARS + 1)))
        self.assertEqual(rejected.exception.status_code, 413)

    def test_backend_unavailable(self):
        with patch.object(app, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(HTTPException) as rejected:
                app.health()
        self.assertEqual(rejected.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
