import unittest

from fastapi import HTTPException

import app


class Encoded(list):
    def tolist(self):
        return list(self)


class FakeModel:
    def get_sentence_embedding_dimension(self):
        return 2

    def encode(self, texts, normalize_embeddings):
        assert normalize_embeddings is True
        return Encoded([[float(index), 1.0] for index, _ in enumerate(texts)])


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.previous_model = app.model
        app.model = FakeModel()

    def tearDown(self):
        app.model = self.previous_model

    def test_health_and_success_payload(self):
        self.assertEqual(app.health()["dimensions"], 2)
        result = app.embeddings(app.EmbeddingRequest(input=["one", "two"]))
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][1]["embedding"], [1.0, 1.0])

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


if __name__ == "__main__":
    unittest.main()
