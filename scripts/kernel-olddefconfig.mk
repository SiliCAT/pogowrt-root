# Load after OpenWrt's root Makefile with make -f.
POGOWRT_KERNEL_CONFIG_MAKEFILE := $(abspath $(lastword $(MAKEFILE_LIST)))

.PHONY: pogowrt-kernel-olddefconfig

ifeq ($(TARGET_BUILD),1)
# The board Makefile supplies the merged config target and ARM toolchain flags.
pogowrt-kernel-olddefconfig: $(STAMP_CONFIGURED)
	+$(KERNEL_MAKE) olddefconfig
else
# Reuse the official kernel_oldconfig prerequisites and exported environment.
pogowrt-kernel-olddefconfig: prepare_kernel_conf
	+$(NO_TRACE_MAKE) -C target/linux/kirkwood \
		-f Makefile -f "$(POGOWRT_KERNEL_CONFIG_MAKEFILE)" \
		TARGET_BUILD=1 pogowrt-kernel-olddefconfig
endif
