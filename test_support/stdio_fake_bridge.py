"""Test-only stdio server restricted to one fake HTTP bridge port."""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

if __name__ == '__main__':
    server.bridge = server.Bridge([int(sys.argv[1])])
    asyncio.run(server.main())
