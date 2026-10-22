#!/usr/bin/env python3
"""Assemble the LuCI rootfs using an already extracted ImageBuilder."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from build_inputs import image_packages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    workspace = args.workspace.resolve()
    builder = workspace / "work/imagebuilder"
    overlay = workspace / "work/luci-files"
    shutil.copytree(project / "images/luci/files", overlay,
                    symlinks=True, ignore=shutil.ignore_patterns(".gitkeep"))
    packages = image_packages(project)
    command = [
        "make", "image", "PROFILE=cloudengines_pogoplugv4",
        "PACKAGES=" + " ".join(packages), "FILES=" + str(overlay),
        "EXTRA_IMAGE_NAME=luci",
    ]
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "assembly-inputs.json").write_text(json.dumps({
        "profile": "cloudengines_pogoplugv4", "packages": packages,
        "files": str(overlay), "command": command,
    }, indent=2) + "\n")
    subprocess.run(command, cwd=builder, check=True)


if __name__ == "__main__":
    main()
