"""Entry point for the thematic analysis pipeline.

Ensures ``src/python`` is importable, then delegates to
``orchestration.cli.main()``.
"""

import sys
from pathlib import Path

# Ensure src/python is on the import path
_src_dir = Path(__file__).parent / "src" / "python"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from orchestration.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
