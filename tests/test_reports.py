"""Exercise report behavior using fixtures, without building or accepting firmware."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
KERNEL = "work/openwrt/build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/linux-6.12.71"
SQUASHFS = "work/openwrt/build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/root.squashfs"


def newc_entry(name, data=b"", mode=0o100755):
    encoded = name.encode() + b"\0"
    fields = [1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
    header = b"070701" + b"".join(f"{value:08x}".encode() for value in fields)
    return (header + encoded + bytes((-(len(header) + len(encoded))) % 4)
            + data + bytes((-len(data)) % 4))


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def write(self, relative, content, mode=None):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        if mode is not None:
            path.chmod(mode)
        return path

    def run_report(self, script, *arguments):
        result = subprocess.run(
            [sys.executable, str(PROJECT / "scripts" / script), *map(str, arguments)],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(set(document), {"observations"})
        self.assertTrue(document["observations"])
        rows = {}
        for row in document["observations"]:
            self.assertEqual(set(row), {"item", "requirement", "observed", "unavailable_reason"})
            self.assertNotIn(row["item"], rows)
            rows[row["item"]] = row
        return rows

    def build_report(self, phase):
        return self.run_report("report-build.py", phase, "--workspace", self.workspace)

    def image_report(self, phase):
        return self.run_report("report-images.py", phase, "--workspace", self.workspace)

    def rootfs_report(self):
        return self.run_report(
            "report-rootfs.py", "--root", self.workspace / "root",
            "--kernel-config", self.workspace / KERNEL / ".config",
            "--sd-init", self.workspace / "project/files/sbin/sd-init",
        )

    def test_all_phases_report_with_missing_build_outputs(self):
        for phase in ["runner", "source", "feeds", "inputs", "resolved-config", "built-configs", "imagebuilder", "evidence", "disk"]:
            with self.subTest(phase=phase):
                self.build_report(phase)
        for phase in ["built", "exported"]:
            with self.subTest(phase=phase):
                rows = self.image_report(phase)
                self.assertIsNotNone(rows["SquashFS superblock"]["unavailable_reason"])
        rows = self.rootfs_report()
        self.assertIsNotNone(rows["File: /sbin/mount.nfs"]["unavailable_reason"])
        self.assertIn("Autoload directory entries", rows)

    def test_configuration_differences_remain_observations(self):
        self.write("project/configs/openwrt.config", "CONFIG_PACKAGE_kmod-fs-nfs-v4=y\nCONFIG_PACKAGE_nfs-utils-v4=y\n")
        config = self.write("work/openwrt/.config", "# CONFIG_PACKAGE_kmod-fs-nfs-v4 is not set\n")
        rows = self.build_report("resolved-config")
        row = rows[f"{config}: CONFIG_PACKAGE_kmod-fs-nfs-v4"]
        self.assertEqual((row["requirement"], row["observed"], row["unavailable_reason"]), ("y", "n", None))
        missing = rows[f"{config}: CONFIG_PACKAGE_nfs-utils-v4"]
        self.assertIsNone(missing["observed"])
        self.assertIsNotNone(missing["unavailable_reason"])
        self.assertEqual((self.workspace / "evidence/openwrt.config.resolved").read_bytes(), config.read_bytes())

    def test_imagebuilder_reports_all_archives_and_differences_without_a_verdict(self):
        config = self.write("work/openwrt/.config", "# CONFIG_IB is not set\nCONFIG_IB_STANDALONE=y\n")
        archive = self.write("work/openwrt/bin/targets/kirkwood/generic/openwrt-imagebuilder-kirkwood-generic.Linux-x86_64.tar.zst", b"source archive fixture")
        versioned = self.write("work/openwrt/bin/targets/kirkwood/generic/openwrt-imagebuilder-25.12.0-kirkwood-generic.Linux-x86_64.tar.zst", b"another archive fixture")
        exported = self.write("delivery/pogov4-imagebuilder-123-1.tar.zst", b"different export fixture")
        rows = self.build_report("imagebuilder")
        self.assertEqual(rows[f"{config}: CONFIG_IB"]["requirement"], "y")
        self.assertEqual(rows[f"{config}: CONFIG_IB"]["observed"], "n")
        self.assertEqual(len(rows["Built ImageBuilder archive candidates"]["observed"]), 2)
        for path in [archive, versioned]:
            self.assertEqual(rows[f"Built ImageBuilder SHA-256: {path}"]["observed"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(rows[f"Exported ImageBuilder SHA-256: {exported}"]["observed"], hashlib.sha256(exported.read_bytes()).hexdigest())
        self.assertEqual(rows[f"Exported ImageBuilder file: {exported}"]["observed"]["bytes"], len(exported.read_bytes()))

    def test_missing_imagebuilder_still_records_export_observations(self):
        rows = self.build_report("imagebuilder")
        self.assertEqual(rows["Built ImageBuilder archive candidates"]["observed"], [])
        self.assertIsNotNone(rows["Built ImageBuilder archive metadata"]["unavailable_reason"])
        self.assertEqual(rows["Exported ImageBuilder archive candidates"]["observed"], [])
        self.assertIsNotNone(rows["Exported ImageBuilder archive metadata"]["unavailable_reason"])

    def test_multiple_kernel_configurations_are_all_reported(self):
        self.write("project/configs/kernel.config", "CONFIG_TARGET_CORE=y\n")
        for release, actual in [("6.12.71", "m"), ("6.12.72", "n")]:
            self.write(KERNEL.replace("6.12.71", release) + "/.config", f"CONFIG_NFS_FS={actual}\nCONFIG_NFS_V4=y\n", 0o640)
        rows = self.build_report("built-configs")
        self.assertEqual(len(rows["kernel configuration candidates"]["observed"]), 2)
        for release, actual in [("6.12.71", "m"), ("6.12.72", "n")]:
            path = self.workspace / KERNEL.replace("6.12.71", release) / ".config"
            self.assertEqual(rows[f"{path}: CONFIG_NFS_FS"]["observed"], actual)
            snapshot = self.workspace / "evidence/configs" / path.relative_to(self.workspace / "work/openwrt")
            self.assertEqual(snapshot.read_bytes(), path.read_bytes())
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o640)

    def test_rootfs_symlinks_stay_in_target_and_later_items_continue(self):
        self.write("root/sbin/mount.nfs", b"not an ELF file", 0o755)
        self.write("root/usr/bin/util-linux-flock", b"target flock", 0o755)
        (self.workspace / "root/sbin/mount.nfs4").symlink_to("/sbin/mount.nfs")
        (self.workspace / "root/usr/bin/flock").symlink_to("/usr/bin/util-linux-flock")
        self.write("root/bin/placeholder", "")
        (self.workspace / "root/bin/sh").symlink_to("/bin/sh")
        self.write("root/etc/modules.d/usb-storage", "usb-storage\n")
        rows = self.rootfs_report()
        self.assertEqual(rows["Entry destination: /sbin/mount.nfs4"]["observed"], "/sbin/mount.nfs")
        self.assertEqual(rows["File: /sbin/mount.nfs"]["observed"]["bytes"], 15)
        self.assertIsNotNone(rows["Entry destination: /bin/sh"]["unavailable_reason"])
        self.assertIsNotNone(rows["ELF header: /sbin/mount.nfs"]["unavailable_reason"])
        self.assertEqual(rows["Autoload contents: usb-storage"]["observed"], "usb-storage\n")

    def test_export_differences_and_unreadable_header_do_not_block_reporting(self):
        original = self.write(SQUASHFS, b"original")
        self.write("artifacts/openwrt/lio-root-aligned.squashfs", b"modified" + b"\0" * 4087 + b"x")
        self.write("artifacts/openwrt/lio-uImage", b"short")
        rows = self.image_report("exported")
        self.assertIsNotNone(rows["uImage header"]["unavailable_reason"])
        prefix = rows["Exported SquashFS original prefix"]
        self.assertEqual(prefix["requirement"]["sha256"], hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertEqual(prefix["observed"]["sha256"], hashlib.sha256(b"modified").hexdigest())
        self.assertEqual(rows["Exported SquashFS appended bytes"]["observed"], {"bytes": 4088, "nonzero_bytes": 1})
        self.assertEqual(original.read_bytes(), b"original")

    def test_initramfs_records_content_and_corrupt_archive_reason(self):
        script = b"#!/bin/sh\nexec /bin/sh\n"
        self.write("project/files/sbin/sd-init", script, 0o755)
        self.write(KERNEL + "/.config", "CONFIG_BLK_DEV_INITRD=y\n")
        archive = newc_entry("sbin/sd-init", script) + newc_entry("TRAILER!!!", mode=0)
        good = self.write(KERNEL + "/usr/initramfs_data.cpio", gzip.compress(archive))
        bad = self.write(KERNEL + "/usr/initramfs_inc_data", b"\x1f\x8b\x08\0\0\0")
        rows = self.image_report("built")
        stored = rows[f"Archived sd-init: {good}"]["observed"]
        self.assertEqual(stored, [{"path": "sbin/sd-init", "bytes": len(script), "mode": "0755", "uid": 0, "gid": 0, "sha256": hashlib.sha256(script).hexdigest()}])
        self.assertIsNotNone(rows[f"Archived sd-init: {bad}"]["unavailable_reason"])

    def test_evidence_snapshots_preserve_input_permissions_and_hidden_config(self):
        script = self.write("project/files/sbin/sd-init", "#!/bin/sh\n", 0o755)
        config = self.write("work/openwrt/.config", "CONFIG_TARGET_kirkwood=y\n", 0o640)
        rows = self.build_report("evidence")
        copied = self.workspace / "evidence/inputs/files/sbin/sd-init"
        self.assertEqual(copied.read_bytes(), script.read_bytes())
        self.assertEqual(copied.stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.workspace / "evidence/openwrt.config.final").read_bytes(), config.read_bytes())
        self.assertIn("Package manifest candidates", rows)


if __name__ == "__main__":
    unittest.main()
