"""Exercise the separate configuration entry with real GNU make and fixture stages."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[1] / "scripts/kernel-olddefconfig.mk"


class KernelConfigStageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = self.root / "calls.log"
        board = self.root / "target/linux/kirkwood"
        (board / "kernel").mkdir(parents=True)
        (self.root / "Makefile").write_text("""NO_TRACE_MAKE := $(MAKE) --no-print-directory
export TEST_KERNEL_CONTEXT := from-root
.PHONY: prepare_kernel_conf
prepare_kernel_conf:
\t@printf 'prepare\\n' >> "$$TEST_PHASE_LOG"
\t@if [ "$${TEST_PREPARE_FAIL:-0}" = 1 ]; then exit 17; fi
\t@touch "$$TEST_TOOLCHAIN_READY"
""")
        (board / "Makefile").write_text("""STAMP_CONFIGURED := $(CURDIR)/.configured
KERNEL_MAKE = $(MAKE) --no-print-directory -C kernel ARCH=arm CROSS_COMPILE=arm-openwrt-linux-muslgnueabi-
.PHONY: FORCE
$(STAMP_CONFIGURED): FORCE
\t@test -f "$$TEST_TOOLCHAIN_READY"
\t@printf 'configure\\n' >> "$$TEST_PHASE_LOG"
\t@touch "$@"
""")
        (board / "kernel/Makefile").write_text(""".PHONY: olddefconfig
olddefconfig:
\t@test "$(ARCH)" = arm
\t@test "$(CROSS_COMPILE)" = arm-openwrt-linux-muslgnueabi-
\t@test "$$TEST_KERNEL_CONTEXT" = from-root
\t@test -f ../.configured
\t@printf 'olddefconfig\\n' >> "$$TEST_PHASE_LOG"
\t@if [ "$${TEST_OLDDEFCONFIG_FAIL:-0}" = 1 ]; then exit 23; fi
""")

    def run_stage(self, **extra_environment):
        return subprocess.run(
            ["make", "--no-print-directory", "-j2", "-f", "Makefile", "-f", str(HELPER),
             "pogowrt-kernel-olddefconfig"],
            cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "TEST_PHASE_LOG": str(self.log),
                 "TEST_TOOLCHAIN_READY": str(self.root / "toolchain-ready"),
                 **extra_environment},
        )

    def test_preparation_configuration_and_olddefconfig_run_in_order(self):
        result = self.run_stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["prepare", "configure", "olddefconfig"])

    def test_preparation_error_prevents_later_execution(self):
        result = self.run_stage(TEST_PREPARE_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text().splitlines(), ["prepare"])
        self.assertFalse((self.root / "target/linux/kirkwood/.configured").exists())

    def test_olddefconfig_execution_error_is_not_hidden(self):
        result = self.run_stage(TEST_OLDDEFCONFIG_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error 23", result.stdout + result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["prepare", "configure", "olddefconfig"])


if __name__ == "__main__":
    unittest.main()
