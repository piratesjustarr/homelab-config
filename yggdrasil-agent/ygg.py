#!/usr/bin/env python3
"""
Yggdrasil CLI entry point
"""

import sys
from pathlib import Path

# Ensure the package is in path
sys.path.insert(0, str(Path(__file__).parent))

from cli import cli

if __name__ == '__main__':
    cli()
