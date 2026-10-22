"""Read image bytes as observations without accepting or rejecting them."""

import hashlib
import struct

from reporting import ObservationUnavailable


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
