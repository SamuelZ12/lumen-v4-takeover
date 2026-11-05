"""Install one executable per discovered program (``clock``, ``serve``, ...) into a bin dir.

    PYTHONPATH=/opt/lumen-cli python3 -m lumen_cli.install /usr/local/bin
"""

import os
import sys
from pathlib import Path

from .registry import discover

_TEMPLATE = """#!/usr/bin/env python3
import sys
sys.path.insert(0, {root!r})
from lumen_cli.main import main
sys.exit(main({program!r}))
"""


def install(bin_dir: Path) -> list[Path]:
    root = str(Path(__file__).resolve().parent.parent)
    written = []
    for program in sorted(discover().programs):
        path = Path(bin_dir) / program
        path.write_text(_TEMPLATE.format(root=root, program=program), encoding="utf-8")
        os.chmod(path, 0o755)
        written.append(path)
    return written


if __name__ == "__main__":
    for path in install(Path(sys.argv[1])):
        print(f"installed {path}")
