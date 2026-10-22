#!/usr/bin/env python3
"""Report build inputs and configurations; observations never select build policy."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess

from reporting import Report, command_output, config_values, digest, file_metadata, report_config


STORAGE_OPTIONS = [
    "MMC", "MMC_BLOCK", "MMC_MVSDIO", "FAT_FS", "VFAT_FS",
    "NLS_CODEPAGE_437", "NLS_ISO8859_1", "BLK_DEV_LOOP",
    "F2FS_FS", "XFS_FS", "SQUASHFS", "OVERLAY_FS",
]

IMAGEBUILDER_PATTERN = "openwrt-imagebuilder-*kirkwood-generic.Linux-x86_64.tar.zst"


def snapshot(report, source, destination):
    def collect():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {**file_metadata(destination), "sha256": digest(destination)}
    report.observe(f"Snapshot: {source}", "Retain the observed configuration as evidence", collect)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["runner", "source", "feeds", "inputs", "resolved-config", "built-configs", "imagebuilder", "evidence", "disk"])
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace
    project = workspace / "project"
    source = workspace / "work/openwrt"
    evidence = workspace / "evidence"
    report = Report()

    if args.phase == "runner":
        for label, requirement, command in [
            ("Architecture", "x86_64", ["uname", "-m"]),
            ("Build user ID", "Non-root user", ["id", "-u"]),
            ("System", "Ubuntu 24.04", ["cat", "/etc/os-release"]),
            ("Kernel", "Record runner kernel", ["uname", "-a"]),
            ("CPU count", "Record available processors; builds use -j2", ["nproc"]),
            ("Memory", "Record available memory", ["free", "-h"]),
            ("Initial disk usage", "Record available disk space", ["df", "-h", str(workspace)]),
        ]:
            report.observe(label, requirement, lambda command=command: command_output(command))

    elif args.phase == "source":
        report.observe("OpenWrt HEAD", os.environ.get("OPENWRT_COMMIT"), lambda: command_output(["git", "rev-parse", "HEAD"], cwd=source))

    elif args.phase == "feeds":
        definitions = report.observe("Feed definitions", "Five feeds at the configured commits", lambda: (source / "feeds.conf").read_text())
        for line in (definitions or "").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 3:
                report.add("Feed definition", "Type, name and pinned source", line, "Cannot extract three fields")
                continue
            feed_type, name, spec = parts
            expected = spec.rsplit("^", 1)[1] if "^" in spec else "No commit specified"
            report.add(f"Feed type: {name}", "src-git", feed_type)
            report.observe(f"Feed HEAD: {name}", expected, lambda name=name: command_output(["git", "rev-parse", "HEAD"], cwd=source / "feeds" / name))
            report.observe(f"Feed index: {name}", "Nonempty package index", lambda name=name: file_metadata(source / "feeds" / f"{name}.index"))

    elif args.phase == "inputs":
        for relative, destination in [
            ("configs/openwrt.config", ".config"),
            ("configs/kernel.config", "env/kernel-config"),
            ("files/sbin/sd-init", "files/sbin/sd-init"),
        ]:
            report.observe(f"Input SHA-256: {relative}", "Record project input digest", lambda relative=relative: digest(project / relative))
            report.observe(f"Imported SHA-256: {destination}", f"Same digest as project/{relative}", lambda destination=destination: digest(source / destination))
        report.observe("Imported sd-init mode", "0755", lambda: file_metadata(source / "files/sbin/sd-init")["mode"])
        def syntax_observation():
            result = subprocess.run(["sh", "-n", str(source / "files/sbin/sd-init")], capture_output=True, text=True)
            return {"command_exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        report.observe("Imported sd-init shell syntax", "sh -n exit code 0", syntax_observation)

    elif args.phase == "resolved-config":
        requirements = report.observe("OpenWrt input options", "Read requirements from the reviewed project fragment", lambda: config_values(project / "configs/openwrt.config")) or {}
        requirements.update({
            "CONFIG_TARGET_ROOTFS_INITRAMFS": "y", "CONFIG_TARGET_ROOTFS_SQUASHFS": "y",
            "CONFIG_EXTERNAL_CPIO": '""', "CONFIG_TARGET_ROOTFS_INITRAMFS_SEPARATE": "n",
        })
        report_config(report, source / ".config", requirements)
        snapshot(report, source / ".config", evidence / "openwrt.config.resolved")

    elif args.phase == "built-configs":
        kernel_requirements = report.observe("Kernel input options", "Read requirements from the reviewed project fragment", lambda: config_values(project / "configs/kernel.config")) or {}
        kernel_requirements.update({f"CONFIG_{key}": "y or m" for key in STORAGE_OPTIONS})
        kernel_requirements.update({"CONFIG_CONFIGFS_FS": "y", "CONFIG_SQUASHFS_XZ": "y", "CONFIG_USB_STORAGE": "m"})
        kernel_requirements.update({
            "CONFIG_NFS_FS": "y or m", "CONFIG_NFS_V4": "y",
            "CONFIG_NFS_V4_1": "y", "CONFIG_NFS_V4_2": "y",
            "CONFIG_SUNRPC": "y or m", "CONFIG_LOCKD": "y or m",
            "CONFIG_GRACE_PERIOD": "y or m", "CONFIG_DNS_RESOLVER": "y or m",
            "CONFIG_F2FS_FS_XATTR": "y",
        })
        busybox_requirements = {f"CONFIG_{key}": "y" for key in ["CMP", "STAT", "FEATURE_STAT_FORMAT", "SWITCH_ROOT", "CHROOT"]}
        for name, pattern, requirements in [
            ("kernel", "build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/linux-6.12.*/.config", kernel_requirements),
            ("busybox", "build_dir/target-arm_xscale_musl_eabi/busybox-default/busybox-1.37.*/.config", busybox_requirements),
        ]:
            candidates = report.observe(f"{name} configuration candidates", "One configuration at the selected target path", lambda pattern=pattern: sorted(source.glob(pattern)))
            for candidate in candidates or []:
                report_config(report, candidate, requirements)
                snapshot(report, candidate, evidence / "configs" / candidate.relative_to(source))
            if not candidates:
                report_config(report, source / pattern, requirements)

    elif args.phase == "imagebuilder":
        report_config(report, source / ".config", {"CONFIG_IB": "y", "CONFIG_IB_STANDALONE": "y"})
        for label, directory, pattern in [
            ("Built", source / "bin/targets/kirkwood/generic", IMAGEBUILDER_PATTERN),
            ("Exported", workspace / "delivery", "pogov4-imagebuilder-*.tar.zst"),
        ]:
            candidates = report.observe(
                f"{label} ImageBuilder archive candidates", {"directory": str(directory), "pattern": pattern},
                lambda directory=directory, pattern=pattern: sorted(directory.glob(pattern)),
            )
            for candidate in candidates or []:
                report.observe(f"{label} ImageBuilder file: {candidate}", "Native standalone ImageBuilder .tar.zst archive", lambda candidate=candidate: file_metadata(candidate))
                requirement = "Record source archive digest" if label == "Built" else "Same digest as the selected built archive; see its SHA-256 observation"
                report.observe(f"{label} ImageBuilder SHA-256: {candidate}", requirement, lambda candidate=candidate: digest(candidate))
            if not candidates:
                report.add(f"{label} ImageBuilder archive metadata", "Record file metadata and SHA-256", unavailable_reason="No archive was located; see the candidate search observation")

    elif args.phase == "evidence":
        report.observe("Project HEAD", "Record the project revision used by this run", lambda: command_output(["git", "rev-parse", "HEAD"], cwd=project))
        for name in ["GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "OPENWRT_TAG", "OPENWRT_COMMIT"]:
            report.add(name, "Record declared run context", os.environ.get(name), None if name in os.environ else "Variable was not supplied to this process")
        for relative in ["configs/openwrt.config", "configs/kernel.config", "files/sbin/sd-init"]:
            snapshot(report, project / relative, evidence / "inputs" / relative)
        snapshot(report, source / "feeds.conf", evidence / "inputs/feeds.conf")
        snapshot(report, source / ".config", evidence / "openwrt.config.final")
        manifests = report.observe("Package manifest candidates", "Record package manifests for the selected target", lambda: sorted((source / "bin/targets/kirkwood/generic").glob("*.manifest")))
        for manifest in manifests or []:
            snapshot(report, manifest, evidence / "manifests" / manifest.name)

    elif args.phase == "disk":
        report.observe("Final disk usage", "Record available disk space", lambda: command_output(["df", "-h", str(workspace)]))

    report.emit()


if __name__ == "__main__":
    main()
