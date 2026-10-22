#!/usr/bin/env python3
"""Report target filesystem observations without executing ARM programs or deciding build policy."""

import argparse
from collections import deque
import glob
import os
from pathlib import Path, PurePosixPath
import re

from reporting import ObservationUnavailable, Report, command_output, config_values, digest, file_metadata
from build_inputs import package_list


class Rootfs:
    def __init__(self, root):
        self.root = root.absolute()

    def resolve(self, name):
        pending = deque(PurePosixPath(name).parts)
        resolved = []
        links = 0
        while pending:
            part = pending.popleft()
            if part == "/":
                resolved = []
            elif part == "..":
                if not resolved:
                    raise ObservationUnavailable(f"Cannot resolve a path outside the target root: {name}")
                resolved.pop()
            elif part != ".":
                candidate = self.root.joinpath(*resolved, part)
                if candidate.is_symlink():
                    links += 1
                    if links > 40:
                        raise ObservationUnavailable(f"Cannot resolve symlink chain: {name}")
                    pending.extendleft(reversed(PurePosixPath(os.readlink(candidate)).parts))
                else:
                    resolved.append(part)
        return self.root.joinpath(*resolved)


def readelf(path, option):
    return command_output(["readelf", "--wide", option, str(path)])


def startup_links(rootfs, service):
    return sorted(
        str(path.relative_to(rootfs.root))
        for path in rootfs.resolve("/etc/rc.d").iterdir()
        if path.name.startswith("S") and path.name.endswith(service)
    )


def report_elf(report, rootfs, name):
    path = report.observe(f"Resolved file: {name}", "Target-root path", lambda: rootfs.resolve(name))
    if path is None:
        return [], []
    report.observe(f"File: {name}", "Nonempty regular file; executable mode for tools", lambda: file_metadata(path))
    def header():
        raw = readelf(path, "--file-header")
        fields = {}
        for key in ["Class", "Data", "Machine"]:
            match = re.search(rf"^\s*{key}:\s*(.*)$", raw, re.MULTILINE)
            fields[key] = match[1] if match else None
        return fields
    report.observe(f"ELF header: {name}", {"Class": "ELF32", "Data": "little endian", "Machine": "ARM"}, header)
    interpreters = report.observe(
        f"ELF interpreter: {name}", "Declared interpreter file present in target root, if applicable",
        lambda: re.findall(r"Requesting program interpreter:\s*([^\]]+)\]", readelf(path, "--program-headers")),
    )
    needed = report.observe(
        f"ELF libraries: {name}", "Declared shared-library files present in target root, if applicable",
        lambda: re.findall(r"\(NEEDED\).*Shared library: \[([^\]]+)\]", readelf(path, "--dynamic")),
    )
    return interpreters or [], needed or []


def report_programs(report, rootfs, extra_tools=()):
    tools = ["/bin/busybox", "/usr/sbin/blkid", "/usr/sbin/losetup", "/usr/bin/util-linux-flock", "/sbin/lvm", "/sbin/mount.nfs"]
    tools.extend(extra_tools)
    for name, target in [
        ("/bin/sh", "/bin/busybox"),
        ("/usr/bin/flock", "/usr/bin/util-linux-flock"),
        ("/sbin/mount.nfs4", "/sbin/mount.nfs"),
    ]:
        report.observe(f"Entry destination: {name}", target, lambda name=name: "/" + str(rootfs.resolve(name).relative_to(rootfs.root)))
    path_file = report.observe("Musl search-path override location", "/etc/ld-musl-arm.path in target root, if present", lambda: rootfs.resolve("/etc/ld-musl-arm.path"))
    search_dirs = None
    override_present = report.observe("Musl search-path override presence", "Optional override file", path_file.exists) if path_file is not None else None
    if override_present is True:
        directories = report.observe("Musl library search paths", "Absolute target paths", lambda: re.split(r"[:\n]", path_file.read_text().strip()))
        search_dirs = directories
    elif override_present is False:
        search_dirs = ["/lib", "/usr/local/lib", "/usr/lib"]
        report.add("Musl library search paths", "Loader defaults when no override file exists", {"override_file": None, "directories": search_dirs})
    else:
        report.add("Musl library search paths", "Target loader search paths", unavailable_reason="Search-path override location could not be resolved")
    pending = deque(tools)
    seen = set()
    while pending:
        name = pending.popleft()
        if name in seen:
            continue
        seen.add(name)
        interpreters, needed = report_elf(report, rootfs, name)
        pending.extend(interpreter.strip() for interpreter in interpreters)
        for library in needed:
            def candidates():
                if search_dirs is None:
                    raise ObservationUnavailable("Target library search directories could not be obtained")
                paths = []
                for directory in search_dirs:
                    if not directory.startswith("/"):
                        raise ObservationUnavailable(f"No target working directory is defined for relative library search path: {directory}")
                    virtual = str(PurePosixPath(directory) / library)
                    if rootfs.resolve(virtual).is_file():
                        paths.append(virtual)
                return sorted(set(paths))
            paths = report.observe(f"Library candidates for {name}: {library}", "Available in the target loader search directories", candidates)
            pending.extend(paths or [])


def report_modules(report, rootfs, kernel_config):
    config_paths = report.observe("Module reference configuration candidates", "One actual kernel configuration", lambda: sorted(Path(path) for path in glob.glob(str(kernel_config))))
    configs = {}
    for path in config_paths or []:
        configs[path] = report.observe(f"Module reference configuration: {path}", "Readable actual kernel configuration", lambda path=path: config_values(path))
    releases = report.observe("Installed module versions", "One version directory for the built kernel", lambda: sorted(p.name for p in rootfs.resolve("/lib/modules").iterdir() if p.is_dir()))
    modules = {}
    for release in releases or []:
        paths = report.observe(f"Module inventory: {release}", "Installed .ko files", lambda release=release: sorted(rootfs.resolve(f"/lib/modules/{release}").rglob("*.ko")))
        for path in paths or []:
            name = path.stem.replace("-", "_")
            modules.setdefault(name, []).append(path)
    requirements = {
        "MMC": "mmc_core", "MMC_BLOCK": "mmc_block", "MMC_MVSDIO": "mvsdio",
        "FAT_FS": "fat", "VFAT_FS": "vfat", "NLS_CODEPAGE_437": "nls_cp437",
        "NLS_ISO8859_1": "nls_iso8859-1", "BLK_DEV_LOOP": "loop", "F2FS_FS": "f2fs",
        "XFS_FS": "xfs", "SQUASHFS": "squashfs", "OVERLAY_FS": "overlay",
        "USB_STORAGE": "usb-storage", "SCSI": "scsi_mod", "BLK_DEV_SD": "sd_mod",
        "NFS_FS": "nfs", "NFS_V4": "nfsv4", "SUNRPC": "sunrpc",
        "LOCKD": "lockd", "GRACE_PERIOD": "grace", "DNS_RESOLVER": "dns_resolver",
    }
    for option, module in requirements.items():
        key = f"CONFIG_{option}"
        observed = [{"source": str(path), "value": values.get(key) if values is not None else None,
                     "unavailable_reason": None if values is not None and key in values else "No value could be obtained from this configuration"}
                    for path, values in configs.items()]
        requirement = "m" if option == "USB_STORAGE" else "y" if option == "NFS_V4" else "y or m"
        report.add(key, requirement, observed, None if observed else "No reference kernel configuration was found")
        module_requirement = "Installed when CONFIG_NFS_FS=m and CONFIG_NFS_V4=y" if option == "NFS_V4" else f"Installed when {key}=m"
        report.add(f"Module candidates: {module}", module_requirement, modules.get(module.replace("-", "_"), []), None if releases is not None else "Module inventory could not be read")
    for paths in modules.values():
        for path in paths:
            virtual = "/" + str(path.relative_to(rootfs.root))
            report.observe(f"Module file: {virtual}", "Nonempty ARM kernel module", lambda virtual=virtual: file_metadata(rootfs.resolve(virtual)))
            report.observe(f"Module ELF header: {virtual}", "ELF32, ARM, little endian", lambda path=path: readelf(rootfs.resolve("/" + str(path.relative_to(rootfs.root))), "--file-header"))
            metadata = report.observe(f"Module metadata: {virtual}", "vermagic and declared dependencies", lambda path=path: readelf(rootfs.resolve("/" + str(path.relative_to(rootfs.root))), "--string-dump=.modinfo"))
            if metadata is None:
                report.add(f"Module version: {virtual}", path.parent.name, unavailable_reason="Module metadata could not be read")
                report.add(f"Module dependencies: {virtual}", "Record declared dependencies and their target files", unavailable_reason="Module metadata could not be read")
                continue
            version = re.search(r"\]\s+vermagic=(\S+)", metadata)
            report.add(f"Module version: {virtual}", path.parent.name, version[1] if version else None, None if version else "No vermagic field found in module metadata")
            dependencies = re.search(r"\]\s+depends=([^\r\n]*)", metadata)
            names = [name for name in dependencies[1].strip().split(",") if name] if dependencies else None
            report.add(f"Module dependencies: {virtual}", "Record declared dependencies and their target files", names, None if dependencies else "No depends field found in module metadata")
            for dependency in names or []:
                report.add(f"Dependency candidates for {virtual}: {dependency}", "Installed module file", modules.get(dependency.replace("-", "_"), []))
    autoload = report.observe("Autoload directory entries", "USB storage autoload configuration in /etc/modules.d", lambda: sorted(rootfs.resolve("/etc/modules.d").iterdir()))
    for entry in autoload or []:
        report.observe(f"Autoload contents: {entry.name}", "Record module names and parameters; usb-storage required among entries", lambda entry=entry: rootfs.resolve("/" + str(entry.relative_to(rootfs.root))).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kernel-config", type=Path, required=True)
    parser.add_argument("--sd-init", type=Path)
    parser.add_argument("--luci", action="store_true", help="Record LuCI files, services and executables")
    parser.add_argument("--recipe", type=Path, help="Record injected files and disabled service startup links")
    args = parser.parse_args()
    report = Report()
    rootfs = Rootfs(args.root)
    report.observe("Target root", "Assembled OpenWrt root directory", lambda: file_metadata(rootfs.root))
    if args.sd_init is not None:
        expected_digest = report.observe("Project sd-init SHA-256", "Record reviewed input digest", lambda: digest(args.sd_init))
        report.observe("Installed sd-init SHA-256", expected_digest or "Same content as project sd-init", lambda: digest(rootfs.resolve("/sbin/sd-init")))
        report.observe("Installed sd-init mode", "0755", lambda: file_metadata(rootfs.resolve("/sbin/sd-init"))["mode"])
    if args.luci:
        for name in ["/www/cgi-bin/luci", "/etc/config/uhttpd", "/etc/init.d/uhttpd", "/etc/init.d/rpcd"]:
            report.observe(f"LuCI file: {name}", "Installed LuCI entry point or service configuration", lambda name=name: file_metadata(rootfs.resolve(name)))
        for service in ["uhttpd", "rpcd"]:
            report.observe(f"LuCI service links: {service}", "Startup links installed by package defaults", lambda service=service: startup_links(rootfs, service))
    if args.recipe is not None:
        inputs = args.recipe / "files"
        paths = report.observe("Recipe file candidates", "Files injected by the selected recipe", lambda: sorted(path for path in inputs.rglob("*") if (path.is_file() or path.is_symlink()) and path.name != ".gitkeep"))
        for path in paths or []:
            name = "/" + str(path.relative_to(inputs))
            expected = report.observe(f"Recipe file SHA-256: {name}", "Record recipe input digest", lambda path=path: digest(path))
            report.observe(f"Installed recipe file: {name}", "Injected file with original permissions", lambda name=name: file_metadata(rootfs.resolve(name)))
            report.observe(f"Installed recipe file SHA-256: {name}", expected or "Same content as recipe input", lambda name=name: digest(rootfs.resolve(name)))
            report.observe(f"Installed recipe file contents: {name}", "Record assembled configuration or first-boot script; runtime effects require boot observations", lambda name=name: rootfs.resolve(name).read_text())
        services = report.observe("Disabled service requirements", "Read the selected recipe's startup exclusions", lambda: package_list(args.recipe / "disabled-services.list"))
        for service in services or []:
            report.observe(f"Service init script: {service}", "Retained package service script", lambda service=service: file_metadata(rootfs.resolve(f"/etc/init.d/{service}")))
            report.observe(f"Disabled service startup links: {service}", [], lambda service=service: startup_links(rootfs, service))
    report_programs(report, rootfs, ["/usr/sbin/uhttpd", "/sbin/rpcd", "/usr/bin/ucode"] if args.luci else [])
    report_modules(report, rootfs, args.kernel_config)
    report.emit()


if __name__ == "__main__":
    main()
