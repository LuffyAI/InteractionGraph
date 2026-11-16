#!/usr/bin/env python3
"""Receive Codex hook events and visualize DotVectorDB conversation memory."""
import argparse
import asyncio
from pathlib import Path
from events.EventServer import EventServer
from dotenv import load_dotenv
load_dotenv()

async def main():
    """Parse command-line arguments and start the event server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--database', default=str(Path(__file__).with_name('ConversationHistory')),
                        help='Dedicated DotVectorDB conversation-memory directory')
    args = parser.parse_args()
    await EventServer.run(args.host, args.port, args.database)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
