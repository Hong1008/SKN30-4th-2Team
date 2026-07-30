"""Cross-platform launcher for the AWS CDK application.

CDK runs this file from the ``infra`` directory.  Keeping the source-path
setup in Python avoids POSIX-only ``PYTHONPATH=...`` syntax and virtualenv
paths such as ``.venv/bin/python``.
"""

from __future__ import annotations

import sys
from pathlib import Path


INFRA_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(INFRA_ROOT / "src"))

# The module constructs the CDK App and calls ``app.synth()`` at import time.
import workshield_infra.cdk_app  # noqa: F401, E402
