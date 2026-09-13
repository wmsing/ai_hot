"""CLI: python -m src.admin [--port 8787]"""

from __future__ import annotations

import argparse
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Hot local admin portal")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8787, help="bind port")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "error: admin deps missing; run: pip install -e '.[admin,dev]'",
            file=sys.stderr,
        )
        return 2
    args = _parse_args(argv)
    from src.admin.app import create_app

    app = create_app()
    print(f"[ai_hot] admin → http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
