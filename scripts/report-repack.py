#!/usr/bin/env python3
"""Record IB provenance, assembly inputs and rootfs bytes without build policy."""

import argparse
import json
import os
from pathlib import Path
import shutil

from build_inputs import IMAGE_NAMES, image_packages, package_list
from image_metadata import padding_bytes, prefix_digest, squashfs_header
from reporting import Report, command_output, digest, file_metadata


def snapshot(report, source, destination):
    def collect():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {**file_metadata(destination), "sha256": digest(destination)}
    report.observe(f"Snapshot: {source}", "Retain assembly input or package manifest", collect)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--image", choices=IMAGE_NAMES, required=True)
    args = parser.parse_args()
    workspace = args.workspace
    project = workspace / "project"
    builder = workspace / "work/imagebuilder"
    evidence = workspace / "evidence"
    report = Report()
    report.add("Selected image recipe", "Explicit pogowrt or luci recipe", args.image)
    for name in ["GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "SOURCE_RUN_ID", "SOURCE_RUN_ATTEMPT"]:
        report.add(name, "Record assembly and IB source context", os.environ.get(name), None if name in os.environ else "Variable was not supplied")
    report.observe("Assembly project HEAD", "Record the recipe revision", lambda: command_output(["git", "rev-parse", "HEAD"], cwd=project))

    def source_run():
        repository = os.environ["GITHUB_REPOSITORY"]
        run_id = os.environ["SOURCE_RUN_ID"]
        attempt = os.environ["SOURCE_RUN_ATTEMPT"]
        data = json.loads(command_output(["gh", "api", f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}"]))
        return {key: data.get(key) for key in ["id", "run_attempt", "head_sha", "head_branch", "path", "event", "html_url"]}

    if all(name in os.environ for name in ["GITHUB_REPOSITORY", "SOURCE_RUN_ID", "SOURCE_RUN_ATTEMPT"]):
        report.observe("IB source workflow run", "Record source commit, workflow and attempt", source_run)
    else:
        report.add("IB source workflow run", "Record source commit, workflow and attempt", unavailable_reason="Repository or source run inputs were not supplied")
    archive = workspace / "work/downloads" / f"pogov4-imagebuilder-{os.environ.get('SOURCE_RUN_ID', '')}-{os.environ.get('SOURCE_RUN_ATTEMPT', '')}.tar.zst"
    report.observe("IB input archive", "Selected run's standalone ImageBuilder", lambda: file_metadata(archive))
    report.observe("IB input archive SHA-256", "Record the archive used by this assembly", lambda: digest(archive))
    report.observe("Requested image packages", "Base package list plus selected recipe", lambda: image_packages(project, args.image))
    report.observe("Requested disabled services", "Services excluded from automatic startup", lambda: package_list(project / "images" / args.image / "disabled-services.list"))
    for relative in ["configs/packages/base.list", f"images/{args.image}/packages.list", f"images/{args.image}/disabled-services.list"]:
        snapshot(report, project / relative, evidence / "inputs" / relative)
    for relative in [".config", ".targetinfo", ".packageinfo"]:
        snapshot(report, builder / relative, evidence / "imagebuilder" / relative)
    configs = report.observe("IB kernel configuration candidates", "Actual configuration of the precompiled kernel", lambda: sorted(builder.glob("build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/linux-6.12.*/.config")))
    for path in configs or []:
        snapshot(report, path, evidence / "imagebuilder" / path.relative_to(builder))
    report.observe("IB package archive inventory", "Precompiled package archives available to this assembly", lambda: [file_metadata(path) for path in sorted((builder / "packages").glob("*.apk"))])

    def overlay_snapshot():
        destination = evidence / "inputs/files"
        shutil.copytree(workspace / "work" / f"{args.image}-files", destination, symlinks=True)
        return str(destination)
    report.observe("Injected files snapshot", "Exact FILES overlay used for assembly", overlay_snapshot)
    manifests = report.observe("IB output manifest candidates", "Installed packages reported by ImageBuilder", lambda: sorted((builder / "bin/targets/kirkwood/generic").glob("*.manifest")))
    for path in manifests or []:
        snapshot(report, path, evidence / "manifests" / path.name)
    original = builder / "build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/root.squashfs"
    exported = workspace / "artifacts" / args.image / f"{args.image}-root-aligned.squashfs"
    for label, path in [("Built", original), ("Exported", exported)]:
        report.observe(f"{label} rootfs file", "SquashFS rootfs", lambda path=path: file_metadata(path))
        report.observe(f"{label} rootfs SHA-256", "Record rootfs digest", lambda path=path: digest(path))
        report.observe(f"{label} SquashFS superblock", {"magic": "0x73717368", "version": "4.0", "compression_id": 4}, lambda path=path: squashfs_header(path))
    size = report.observe("Original rootfs bytes", "Unmodified source image length N", lambda: original.stat().st_size)
    expected = report.observe("Original rootfs digest", "Record source digest for the exported prefix", lambda: digest(original))
    aligned = ((size + 4095) // 4096) * 4096 if size is not None else None
    report.observe("Exported rootfs bytes", aligned if aligned is not None else "ceil(N / 4096) * 4096", lambda: exported.stat().st_size)
    report.observe("Exported rootfs alignment remainder", 0, lambda: exported.stat().st_size % 4096)
    if size is not None:
        report.observe("Exported rootfs original prefix", {"bytes_hashed": size, "sha256": expected}, lambda: prefix_digest(exported, size))
        report.observe("Exported rootfs appended bytes", {"bytes": aligned - size, "nonzero_bytes": 0}, lambda: padding_bytes(exported, size))
    else:
        for label in ["Exported rootfs original prefix", "Exported rootfs appended bytes"]:
            report.add(label, "Record source prefix and zero padding", unavailable_reason="Original image length could not be obtained")
    archives = report.observe("Built rootfs tar archive candidates", "Native rootfs.tar.gz produced with CONFIG_TARGET_ROOTFS_TARGZ=y", lambda: sorted((builder / "bin/targets/kirkwood/generic").glob("*-rootfs.tar.gz")))
    archive_digests = []
    for archive in archives or []:
        archive_digests.append(report.observe(f"Built rootfs tar archive SHA-256: {archive}", "Record native archive digest", lambda archive=archive: digest(archive)))
    archive = workspace / "artifacts" / args.image / f"{args.image}-rootfs.tar.gz"
    report.observe("Exported rootfs tar archive", "Unmodified copy of the native rootfs.tar.gz archive", lambda: file_metadata(archive))
    expected_archive_digest = archive_digests[0] if len(archive_digests) == 1 else None
    report.observe("Exported rootfs tar archive SHA-256", expected_archive_digest or "Same digest as the built rootfs tar archive; see its observation", lambda: digest(archive))
    report.emit()


if __name__ == "__main__":
    main()
