#!/usr/bin/env python3
"""Compose the reviewed fragments into the OpenWrt input configuration."""

import argparse
from pathlib import Path

from build_inputs import source_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(source_config(args.project))


if __name__ == "__main__":
    main()
