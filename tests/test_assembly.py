"""Exercise configuration composition and IB assembly with temporary fixtures."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from build_inputs import image_packages, package_list, source_config


class AssemblyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pogowrt assembly ")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.project = self.workspace / "project"
        self.write("project/configs/openwrt.config", "CONFIG_TARGET_kirkwood=y\n")
        self.write("project/configs/packages/base.list", "# shared\nflock\nkmod-fs-nfs-v4\nflock # duplicate\n\n")
        self.write("project/configs/ib-extra.config", "CONFIG_PACKAGE_luci=m\n")
        self.write("project/images/luci/packages.list", "luci\nflock\n")

    def write(self, relative, content):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def script(self, name, *arguments):
        return subprocess.run(
            [sys.executable, str(PROJECT / "scripts" / name), *map(str, arguments)],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_source_composition_keeps_base_installed_and_luci_compile_only(self):
        original = (self.project / "configs/openwrt.config").read_bytes()
        output = self.workspace / ".config"
        result = self.script("prepare-build-config.py", "--project", self.project, "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIG_TARGET_kirkwood=y\n", output.read_text())
        self.assertEqual(output.read_text().count("CONFIG_PACKAGE_flock=y"), 1)
        self.assertIn("CONFIG_PACKAGE_kmod-fs-nfs-v4=y\n", output.read_text())
        self.assertIn("CONFIG_PACKAGE_luci=m\n", output.read_text())
        self.assertNotIn("CONFIG_PACKAGE_luci=y", output.read_text())
        self.assertEqual((self.project / "configs/openwrt.config").read_bytes(), original)

    def test_repository_recipes_share_the_same_base_packages(self):
        packages = package_list(PROJECT / "configs/packages/base.list")
        merged = source_config(PROJECT)
        for name in packages:
            self.assertIn(f"CONFIG_PACKAGE_{name}=y\n", merged)
            self.assertIn(name, image_packages(PROJECT))
        self.assertIn("luci", image_packages(PROJECT))
        self.assertIn("CONFIG_PACKAGE_luci=m\n", merged)
        assignments = [line.split("=", 1)[0] for line in merged.splitlines() if line.startswith("CONFIG_")]
        self.assertEqual(len(assignments), len(set(assignments)))

    def test_assembly_passes_packages_and_preserves_overlay_permissions_and_links(self):
        self.write("project/images/luci/files/.gitkeep", "")
        self.write("project/images/luci/files/.hidden", "keep me\n")
        script = self.write("project/images/luci/files/etc/uci-defaults/90-local", "#!/bin/sh\n")
        script.chmod(0o755)
        (script.parent / "91-link").symlink_to("90-local")
        self.write("work/imagebuilder/Makefile", """.PHONY: image
image:
\t@test "$(PROFILE)" = cloudengines_pogoplugv4
\t@test "$(PACKAGES)" = 'flock kmod-fs-nfs-v4 luci'
\t@test "$(EXTRA_IMAGE_NAME)" = luci
\t@test -f "$(FILES)/.hidden"
\t@test -x "$(FILES)/etc/uci-defaults/90-local"
\t@test -L "$(FILES)/etc/uci-defaults/91-link"
\t@test ! -e "$(FILES)/.gitkeep"
\t@touch invoked
""")
        result = self.script("build-rootfs.py", "--project", self.project, "--workspace", self.workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.workspace / "work/imagebuilder/invoked").exists())
        context = json.loads((self.workspace / "evidence/assembly-inputs.json").read_text())
        self.assertEqual(context["packages"], ["flock", "kmod-fs-nfs-v4", "luci"])

    def test_assembly_failure_retains_inputs_and_exposes_make_error(self):
        self.write("project/images/luci/files/.gitkeep", "")
        self.write("work/imagebuilder/Makefile", "image:\n\t@exit 23\n")
        result = self.script("build-rootfs.py", "--project", self.project, "--workspace", self.workspace)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error 23", result.stderr)
        self.assertTrue((self.workspace / "evidence/assembly-inputs.json").is_file())

    def test_export_preserves_source_and_zero_extends_only_copy(self):
        for length in [4096, 4097]:
            with self.subTest(length=length):
                content = b"x" * length
                original = self.write("original.squashfs", content)
                output = self.workspace / "output/root.squashfs"
                record = self.workspace / "evidence/export.json"
                result = self.script("export-rootfs.py", "--source", original, "--output", output, "--record", record)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(original.read_bytes(), content)
                self.assertEqual(output.read_bytes(), content + bytes((-length) % 4096))
                self.assertEqual(json.loads(record.read_text())["original_copy_bytes"], length)

    def test_missing_export_source_exposes_copy_error(self):
        result = self.script("export-rootfs.py", "--source", self.workspace / "missing", "--output", self.workspace / "output/root.squashfs", "--record", self.workspace / "record.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.workspace / "record.json").exists())

    def test_repack_report_retains_differences_as_observations(self):
        original = self.write("work/imagebuilder/build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/root.squashfs", b"original")
        self.write("artifacts/luci/luci-root-aligned.squashfs", b"modified" + bytes(4088))
        result = self.script("report-repack.py", "--workspace", self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {}
        for row in json.loads(result.stdout)["observations"]:
            self.assertEqual(set(row), {"item", "requirement", "observed", "unavailable_reason"})
            rows[row["item"]] = row
        self.assertEqual(rows["Exported rootfs original prefix"]["requirement"]["sha256"], hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertEqual(rows["Exported rootfs original prefix"]["observed"]["sha256"], hashlib.sha256(b"modified").hexdigest())
        self.assertIsNotNone(rows["IB input archive"]["unavailable_reason"])
        self.assertEqual(rows["Requested image packages"]["observed"], ["flock", "kmod-fs-nfs-v4", "luci"])

    def test_missing_ib_outputs_and_luci_files_still_produce_reports(self):
        result = self.script("report-repack.py", "--workspace", self.workspace)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {row["item"]: row for row in json.loads(result.stdout)["observations"]}
        self.assertIsNotNone(rows["Original rootfs bytes"]["unavailable_reason"])
        result = self.script("report-rootfs.py", "--root", self.workspace / "missing-root", "--kernel-config", self.workspace / "missing-config", "--luci")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {row["item"]: row for row in json.loads(result.stdout)["observations"]}
        self.assertIsNotNone(rows["LuCI file: /www/cgi-bin/luci"]["unavailable_reason"])
        self.assertIn("File: /usr/sbin/uhttpd", rows)
        self.assertNotIn("Installed sd-init mode", rows)


if __name__ == "__main__":
    unittest.main()
