import pytest

from lumen_dev.harness import Run


@pytest.fixture
def run(tmp_path):
    """A fresh in-process sidecar seeded from the task's spec.yaml."""
    with Run(tmp_path) as r:
        yield r
