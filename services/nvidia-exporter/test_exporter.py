import subprocess
import unittest
from unittest.mock import patch

import exporter


class ExporterTests(unittest.TestCase):
    def test_healthy_metrics(self):
        result = subprocess.CompletedProcess([], 0, "0, Test GPU, 25, 100, 1000, 55, 30\n", "")
        with patch("exporter.subprocess.run", return_value=result):
            body, healthy = exporter.metrics()
        self.assertTrue(healthy)
        self.assertIn("nvidia_gpu_up 1", body)
        self.assertIn("nvidia_gpu_memory_total_bytes", body)
        self.assertIn("1048576000.0", body)

    def test_failed_command_reports_down(self):
        with patch("exporter.subprocess.run", side_effect=subprocess.CalledProcessError(1, "nvidia-smi")):
            body, healthy = exporter.metrics()
        self.assertFalse(healthy)
        self.assertIn("nvidia_gpu_up 0", body)


if __name__ == "__main__":
    unittest.main()
