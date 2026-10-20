"""Entry point: python backend/run_benchmark.py run --set primary --puzzles 5"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
