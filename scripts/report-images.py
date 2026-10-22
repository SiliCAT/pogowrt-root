#!/usr/bin/env python3
"""Report image metadata, initramfs inputs and exported bytes without selecting build policy."""

import argparse
import bz2
import gzip
import hashlib
import lzma
from pathlib import Path
import stat
import struct
import zlib

from reporting import ObservationUnavailable, Report, digest, file_metadata, report_config


UIMAGE = Path("bin/targets/kirkwood/generic/openwrt-kirkwood-generic-cloudengines_pogoplugv4-initramfs-uImage")
SQUASHFS = Path("build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/root.squashfs")
KERNEL_PATTERN = "build_dir/target-arm_xscale_musl_eabi/linux-kirkwood_generic/linux-6.12.*/.config"


def prefix_digest(path, length):
    checksum = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while count < length:
            chunk = stream.read(min(1024 * 1024, length - count))
            if not chunk:
                break
            count += len(chunk)
            checksum.update(chunk)
    return {"bytes_hashed": count, "sha256": checksum.hexdigest()}


def padding_bytes(path, offset):
    count = 0
    nonzero = 0
    with path.open("rb") as stream:
        stream.seek(offset)
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            nonzero += len(chunk) - chunk.count(0)
    return {"bytes": count, "nonzero_bytes": nonzero}


def uimage_header(path):
    with path.open("rb") as stream:
        header = stream.read(64)
    if len(header) != 64:
        raise ObservationUnavailable(f"A 64-byte uImage header could not be read; obtained {len(header)} bytes")
    magic, hcrc, timestamp, size, load, entry, dcrc, os_id, arch, kind, compression, name = struct.unpack(
        ">7I4B32s", header,
    )
    return {
        "magic": f"0x{magic:08x}", "declared_header_crc32": f"{hcrc:08x}",
        "computed_header_crc32": f"{zlib.crc32(header[:4] + bytes(4) + header[8:]) & 0xffffffff:08x}",
        "timestamp": timestamp, "declared_payload_bytes": size,
        "load_address": f"0x{load:08x}", "entry_address": f"0x{entry:08x}",
        "declared_payload_crc32": f"{dcrc:08x}", "os_id": os_id,
        "architecture_id": arch, "image_type_id": kind, "compression_id": compression,
        "name": name.split(b"\0", 1)[0].decode("utf-8", errors="replace"),
    }


def payload_crc(path, size):
    count = 0
    checksum = 0
    with path.open("rb") as stream:
        stream.seek(64)
        while count < size:
            chunk = stream.read(min(1024 * 1024, size - count))
            if not chunk:
                break
            checksum = zlib.crc32(chunk, checksum)
            count += len(chunk)
    return {"bytes_read": count, "crc32": f"{checksum & 0xffffffff:08x}"}


def squashfs_header(path):
    with path.open("rb") as stream:
        header = stream.read(96)
    if len(header) != 96:
        raise ObservationUnavailable(f"A 96-byte SquashFS superblock could not be read; obtained {len(header)} bytes")
    fields = struct.unpack("<5I6H8Q", header)
    return {
        "magic": f"0x{fields[0]:08x}", "inode_count": fields[1],
        "creation_time": fields[2], "block_size": fields[3], "fragment_count": fields[4],
        "compression_id": fields[5], "version": f"{fields[9]}.{fields[10]}",
        "filesystem_bytes_used": fields[12],
    }


def image_observations(report, uimage, squashfs):
    for name, path in [("initramfs-uImage", uimage), ("SquashFS", squashfs)]:
        report.observe(f"{name} file", "Nonempty image at the specified path", lambda path=path: file_metadata(path))
        report.observe(f"{name} SHA-256", "Record image digest", lambda path=path: digest(path))
    header = report.observe("uImage header", {"magic": "0x27051956", "os_id": 5, "architecture_id": 2, "image_type_id": 2}, lambda: uimage_header(uimage))
    report.observe("uImage header CRC32", header["declared_header_crc32"] if header else "Declared header CRC32", lambda: uimage_header(uimage)["computed_header_crc32"])
    if header is not None:
        report.observe("uImage payload CRC32", {"bytes": header["declared_payload_bytes"], "crc32": header["declared_payload_crc32"]}, lambda: payload_crc(uimage, header["declared_payload_bytes"]))
    else:
        report.add("uImage payload CRC32", "Declared payload CRC32", unavailable_reason="Payload size could not be obtained from the header")
    report.observe("SquashFS superblock", {"magic": "0x73717368", "version": "4.0", "compression_id": 4}, lambda: squashfs_header(squashfs))


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ObservationUnavailable(f"Archive ended while reading {length} bytes; obtained {len(data)}")
    return data


def initramfs_sd_init(path):
    with path.open("rb") as source:
        signature = source.read(6)
    opener = path.open
    if signature.startswith(b"\x1f\x8b"):
        opener = lambda mode: gzip.open(path, mode)
    elif signature.startswith(b"\xfd7zXZ\x00"):
        opener = lambda mode: lzma.open(path, mode)
    elif signature.startswith(b"BZh"):
        opener = lambda mode: bz2.open(path, mode)
    elif signature not in {b"070701", b"070702"}:
        raise ObservationUnavailable(f"Archive metadata reader has no decoder for leading bytes {signature.hex()}")
    try:
        with opener("rb") as stream:
            return cpio_sd_init(stream)
    except (EOFError, lzma.LZMAError, zlib.error) as error:
        raise ObservationUnavailable(f"Compressed archive metadata could not be read: {error}") from error


def cpio_sd_init(stream):
    entries = []
    while True:
        header = read_exact(stream, 110)
        if header[:6] not in {b"070701", b"070702"}:
            raise ObservationUnavailable("Next archive entry could not be interpreted as a newc header")
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        mode, uid, gid, length, name_length = fields[1], fields[2], fields[3], fields[6], fields[11]
        if not 0 < name_length <= 1024 * 1024:
            raise ObservationUnavailable(f"Archive filename length is outside this metadata reader's supported range: {name_length}")
        raw_name = read_exact(stream, name_length)
        name = raw_name.rstrip(b"\0").decode("utf-8", errors="replace")
        read_exact(stream, (-(110 + name_length)) % 4)
        checksum = hashlib.sha256()
        remaining = length
        while remaining:
            chunk = read_exact(stream, min(remaining, 1024 * 1024))
            checksum.update(chunk)
            remaining -= len(chunk)
        read_exact(stream, (-length) % 4)
        if name.removeprefix("./").lstrip("/") == "sbin/sd-init":
            entries.append({"path": name, "bytes": length, "mode": f"{stat.S_IMODE(mode):04o}", "uid": uid, "gid": gid, "sha256": checksum.hexdigest()})
        if name == "TRAILER!!!":
            return entries


def report_initramfs(report, source, project):
    expected = report.observe("Project sd-init SHA-256", "Record reviewed input digest", lambda: digest(project / "files/sbin/sd-init"))
    configs = report.observe("Initramfs kernel configuration candidates", "Actual configuration for the selected kernel", lambda: sorted(source.glob(KERNEL_PATTERN)))
    for config in configs or []:
        report_config(report, config, {
            "CONFIG_BLK_DEV_INITRD": "y", "CONFIG_INITRAMFS_SOURCE": str(source / "build_dir/target-arm_xscale_musl_eabi/root-kirkwood"),
            "CONFIG_INITRAMFS_COMPRESSION_NONE": "y",
        })
        kernel = config.parent
        for name, requirement in [
            (".initramfs_data.cpio.cmd", "Generation command records the injected root directory"),
            (".initramfs_inc_data.cmd", "Command for the data included in the kernel"),
        ]:
            report.observe(f"Initramfs command: {kernel / 'usr' / name}", requirement, lambda name=name, kernel=kernel: (kernel / "usr" / name).read_text())
        report.observe(f"sd-init archive dependency: {kernel}", "Record the injected sd-init among initramfs input dependencies", lambda kernel=kernel: [line for line in (kernel / "usr/.initramfs_data.cpio.d").read_text().splitlines() if "sd-init" in line])
        for archive in [kernel / "usr/initramfs_data.cpio", kernel / "usr/initramfs_inc_data"]:
            report.observe(f"Initramfs data file: {archive}", "Archive data produced by the kernel build", lambda archive=archive: file_metadata(archive))
            report.observe(f"Initramfs data SHA-256: {archive}", "Record data digest", lambda archive=archive: digest(archive))
            report.observe(f"Archived sd-init: {archive}", {"path": "sbin/sd-init", "mode": "0755", "sha256": expected}, lambda archive=archive: initramfs_sd_init(archive))
    if not configs:
        report.add("Initramfs source and archived sd-init", "Record configuration, generation commands and archive entries", unavailable_reason="No actual kernel configuration was located; candidate paths are recorded above")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["built", "exported"])
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    source = args.workspace / "work/openwrt"
    project = args.workspace / "project"
    report = Report()
    original_uimage, original_squashfs = source / UIMAGE, source / SQUASHFS
    if args.phase == "built":
        image_observations(report, original_uimage, original_squashfs)
        report_initramfs(report, source, project)
    else:
        output = args.workspace / "artifacts/openwrt"
        uimage = output / "lio-uImage"
        squashfs = output / "lio-root-aligned.squashfs"
        image_observations(report, uimage, squashfs)
        expected_uimage_digest = report.observe("Build uImage SHA-256", "Record source digest for exported uImage", lambda: digest(original_uimage))
        report.observe("Exported uImage SHA-256", expected_uimage_digest or "Same content as build uImage", lambda: digest(uimage))
        size = report.observe("Build SquashFS bytes", "Original unmodified image length N", lambda: original_squashfs.stat().st_size)
        expected_digest = report.observe("Build SquashFS SHA-256", "Original unmodified image digest", lambda: digest(original_squashfs))
        aligned = ((size + 4095) // 4096) * 4096 if size is not None else None
        report.observe("Exported SquashFS bytes", aligned if aligned is not None else "ceil(N / 4096) * 4096", lambda: squashfs.stat().st_size)
        report.observe("Exported SquashFS length remainder", {"modulus": 4096, "remainder": 0}, lambda: squashfs.stat().st_size % 4096)
        if size is not None:
            report.observe("Exported SquashFS original prefix", {"bytes_hashed": size, "sha256": expected_digest}, lambda: prefix_digest(squashfs, size))
            report.observe("Exported SquashFS appended bytes", {"bytes": aligned - size, "nonzero_bytes": 0}, lambda: padding_bytes(squashfs, size))
        else:
            for item in ["Exported SquashFS original prefix", "Exported SquashFS appended bytes"]:
                report.add(item, "Record original prefix and appended padding", unavailable_reason="Original image length could not be obtained")
    report.emit()


if __name__ == "__main__":
    main()
