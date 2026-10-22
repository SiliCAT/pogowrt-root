#!/usr/bin/env python3
"""Assemble the selected rootfs recipe using an extracted ImageBuilder."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from build_inputs import IMAGE_NAMES, image_packages, package_list


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--image", choices=IMAGE_NAMES, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    workspace = args.workspace.resolve()
    builder = workspace / "work/imagebuilder"
    recipe = project / "images" / args.image
    overlay = workspace / "work" / f"{args.image}-files"
    shutil.copytree(recipe / "files", overlay,
                    symlinks=True, ignore=shutil.ignore_patterns(".gitkeep"))
    packages = image_packages(project, args.image)
    disabled_services = package_list(recipe / "disabled-services.list")
    command = [
        "make", "image", "PROFILE=cloudengines_pogoplugv4",
        "PACKAGES=" + " ".join(packages), "FILES=" + str(overlay),
        "EXTRA_IMAGE_NAME=" + args.image,
        "DISABLED_SERVICES=" + " ".join(disabled_services),
        "CONFIG_TARGET_ROOTFS_TARGZ=y",
    ]
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "assembly-inputs.json").write_text(json.dumps({
        "image": args.image, "profile": "cloudengines_pogoplugv4", "packages": packages,
        "disabled_services": disabled_services,
        "files": str(overlay), "command": command,
    }, indent=2) + "\n")
    subprocess.run(command, cwd=builder, check=True)


if __name__ == "__main__":
    main()
