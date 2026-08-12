import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import HTTPException

import app


AUTHORIZATION = f"Bearer {app.API_KEY}"


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=app.ROOT)
        self.project = Path(self.temp.name).name

    def tearDown(self):
        self.temp.cleanup()

    def test_authentication_and_schema_are_protected(self):
        app.auth(None, AUTHORIZATION)
        with self.assertRaises(HTTPException) as rejected:
            app.openapi_schema(None, None)
        self.assertEqual(rejected.exception.status_code, 401)
        self.assertEqual(app.openapi_schema(None, AUTHORIZATION)["info"]["version"], "1.1.0")

    def test_atomic_write_append_and_hash(self):
        relative = f"{self.project}/note.txt"
        app.fs_write(app.WriteReq(path=relative, content="first"), None, AUTHORIZATION)
        result = app.fs_write(app.WriteReq(path=relative, content=" second", append=True), None, AUTHORIZATION)
        self.assertEqual((app.ROOT / relative).read_text(), "first second")
        self.assertEqual(result["bytes"], 12)
        self.assertEqual(app.fs_hash(relative, None, AUTHORIZATION)["sha256"], result["sha256"])

    def test_shell_environment_excludes_gateway_secret(self):
        result = app.shell_exec(
            app.ShellReq(command='printf "%s" "${AGENT_GATEWAY_KEY-unset}"', project=self.project),
            None,
            AUTHORIZATION,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "unset")

    def test_timeout_terminates_descendant_process_group(self):
        result = app.shell_exec(
            app.ShellReq(command="(sleep 2; echo orphan > orphan.txt) & wait", project=self.project, timeout_seconds=1),
            None,
            AUTHORIZATION,
        )
        self.assertEqual(result["exit_code"], 124)
        time.sleep(2)
        self.assertFalse((Path(self.temp.name) / "orphan.txt").exists())

    def test_audit_reader_skips_truncated_records(self):
        audit_path = app.ARTIFACTS / "agent-audit.jsonl"
        audit_path.write_text('{"valid":1}\n{"truncated"')
        events = app.transparency_audit(10, None, AUTHORIZATION)["events"]
        self.assertIn({"valid": 1}, events)

    def test_url_credentials_and_fragments_are_rejected(self):
        for url in ("https://user:secret@example.com/", "https://example.com/#secret"):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                app.checked_url(url)


if __name__ == "__main__":
    unittest.main()
