#!/usr/bin/env python3

import argparse
import sys
from python_on_whales import docker

def main():
    parser = argparse.ArgumentParser(
        description="Launch claude-agent instances",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--scale',
        type=int,
        default=1,
        help='Number of claude-agent instances to launch (default: 1)'
    )

    args = parser.parse_args()

    # Validate scale is positive
    if args.scale < 1:
        print(f"Error: --scale must be a positive integer, got: {args.scale}", file=sys.stderr)
        sys.exit(1)

    print(f"Launching {args.scale} claude-agent instances...")

    try:
        # Scale the service
        docker.compose.up(scales={'claude-agent': args.scale}, detach=True)

        print("\nPort mappings:")

        # Get port mappings for each instance
        for i in range(1, args.scale + 1):
            try:
                host, port = docker.compose.port('claude-agent', 9999, index=i)
                print(f"claude-agent_{i} -> {host}:{port}")
            except Exception:
                print(f"claude-agent_{i} -> (port not found)")

    except Exception as e:
        print(f"Error running docker compose: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
