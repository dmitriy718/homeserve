import threading
import time
import unittest

from fastapi.testclient import TestClient

import app


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        with app.LOCK:
            app.LEASE = None
            app.QUEUE.clear()
            for kind in app.ACQUISITIONS:
                app.ACQUISITIONS[kind] = 0
            app.RELEASES = 0
            app.EXPIRATIONS = 0
            app.WAIT_COUNT = 0
            app.WAIT_SUM = 0.0

    def acquire(self, holder="holder-a", kind="llm", ttl=120, **params):
        return self.client.post(
            "/leases",
            json={"holder": holder, "kind": kind, "ttl_seconds": ttl},
            params=params,
        )

    def test_acquire_and_release_cycle(self):
        response = self.acquire()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["granted"])
        state = self.client.get("/state").json()
        self.assertEqual(state["current"]["holder"], "holder-a")
        self.assertEqual(state["current"]["kind"], "llm")
        self.assertEqual(state["history"]["acquisitions_total"]["llm"], 1)

        released = self.client.delete("/leases/holder-a")
        self.assertEqual(released.status_code, 200)
        self.assertTrue(released.json()["released"])
        self.assertIsNone(self.client.get("/state").json()["current"])
        self.assertEqual(self.client.delete("/leases/holder-a").status_code, 404)

    def test_conflict_returns_409_with_queue_position(self):
        self.acquire("first", "llm")
        conflict = self.acquire("second", "image")
        self.assertEqual(conflict.status_code, 409)
        detail = conflict.json()["detail"]
        self.assertFalse(detail["granted"])
        self.assertEqual(detail["current_holder"], "first")
        self.assertEqual(detail["queue_position"], 1)

        # A third requester queues behind; position is stable across retries.
        self.assertEqual(self.acquire("third", "other").json()["detail"]["queue_position"], 2)
        self.assertEqual(self.acquire("second", "image").json()["detail"]["queue_position"], 1)
        queue = self.client.get("/state").json()["queue"]
        self.assertEqual([q["holder"] for q in queue], ["second", "third"])

    def test_reacquire_by_current_holder_is_idempotent_refresh(self):
        self.acquire("only", "image", ttl=60)
        refreshed = self.acquire("only", "image", ttl=600)
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json()["ttl_seconds"], 600)
        self.assertEqual(self.client.get("/state").json()["history"]["acquisitions_total"]["image"], 1)

    def test_wait_true_is_granted_after_release(self):
        self.acquire("blocker", "llm")
        outcome = {}

        def waiter():
            outcome["response"] = self.acquire("waiter", "image", wait="true", wait_timeout=10)

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.3)
        self.assertNotIn("response", outcome)  # still long-polling
        self.client.delete("/leases/blocker")
        thread.join(timeout=10)
        self.assertEqual(outcome["response"].status_code, 200)
        self.assertEqual(outcome["response"].json()["holder"], "waiter")
        state = self.client.get("/state").json()
        self.assertEqual(state["current"]["holder"], "waiter")
        self.assertEqual(state["history"]["wait_samples"], 1)

    def test_wait_true_times_out_with_409(self):
        self.acquire("blocker", "llm", ttl=120)
        response = self.acquire("impatient", "image", wait="true", wait_timeout=1)
        self.assertEqual(response.status_code, 409)
        self.assertTrue(response.json()["detail"]["timed_out"])

    def test_ttl_expiry_reclaims_lease_and_serves_queue(self):
        self.acquire("crashy", "llm", ttl=1)
        self.assertEqual(self.acquire("queued", "image").status_code, 409)
        time.sleep(1.3)
        state = self.client.get("/state").json()  # lazy expiry on any request
        self.assertEqual(state["history"]["expirations_total"], 1)
        # The queued holder was granted automatically when the lease was reclaimed.
        self.assertEqual(state["current"]["holder"], "queued")
        self.assertEqual(state["current"]["kind"], "image")
        # The expired holder is told it no longer holds anything.
        self.assertEqual(self.client.post("/leases/crashy/heartbeat").status_code, 404)

    def test_heartbeat_refreshes_ttl(self):
        self.acquire("steady", "other", ttl=120)
        response = self.client.post("/leases/steady/heartbeat")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expires_in_seconds"], 120.0)
        self.assertEqual(self.client.post("/leases/nobody/heartbeat").status_code, 404)

    def test_metrics_shape(self):
        self.acquire("first", "llm")
        self.acquire("second", "image")  # queues
        body = self.client.get("/metrics").text
        self.assertIn('# TYPE gpu_lease_active gauge', body)
        self.assertIn('gpu_lease_active{holder="first",kind="llm"} 1', body)
        self.assertIn('gpu_lease_started_unixtime{holder="first",kind="llm"}', body)
        self.assertIn("gpu_lease_queue_depth 1", body)
        self.assertIn('gpu_lease_acquisitions_total{kind="llm"} 1', body)
        self.assertIn('gpu_lease_acquisitions_total{kind="image"} 0', body)
        self.assertIn("gpu_lease_wait_seconds_count 0", body)
        self.assertIn("gpu_lease_releases_total 0", body)
        self.assertIn("gpu_lease_expirations_total 0", body)


if __name__ == "__main__":
    unittest.main()
