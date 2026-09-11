from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .xhs_video import _download


def emit(message: str) -> None:
    print(message, flush=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("用法: python -m mvp.xhs_video_worker <request.json> <raw-dir>")
    request_path = Path(sys.argv[1]).resolve()
    raw = Path(sys.argv[2]).resolve()
    items = json.loads(request_path.read_text(encoding="utf-8"))
    asyncio.run(_download(items, raw, emit))


if __name__ == "__main__":
    main()
