#!/usr/bin/env python3
"""Copy a rootfs and zero-extend only the copy to a 4096-byte boundary."""

import argparse
import json
from pathlib import Path
import shutil


def export_rootfs(source, output, record):
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)
    original = output.stat().st_size
    aligned = ((original + 4095) // 4096) * 4096
    with output.open("r+b") as stream:
        stream.truncate(aligned)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({
        "original_copy_bytes": original,
        "requested_aligned_bytes": aligned,
        "alignment_bytes": 4096,
    }) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    export_rootfs(args.source, args.output, args.record)


if __name__ == "__main__":
    main()
