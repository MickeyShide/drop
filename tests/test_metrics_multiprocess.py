import os
import subprocess
import sys
from pathlib import Path


def test_worker_metrics_are_visible_from_another_process(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PROMETHEUS_MULTIPROC_DIR"] = str(tmp_path)

    worker = subprocess.run(
        [
            sys.executable,
            "-c",
            "from drop.metrics import CELERY_TASK_FAILURES_TOTAL; "
            "CELERY_TASK_FAILURES_TOTAL.labels(task_name='drop.delete_file').inc()",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert worker.returncode == 0, worker.stderr

    collector = subprocess.run(
        [
            sys.executable,
            "-c",
            "from drop.metrics import generate_metrics; "
            "print(generate_metrics().decode(), end='')",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collector.returncode == 0, collector.stderr
    assert (
        'celery_task_failures_total{task_name="drop.delete_file"} 1.0'
        in collector.stdout
    )
