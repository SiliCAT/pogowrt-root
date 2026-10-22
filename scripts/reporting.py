"""Collect observations without evaluating requirements or controlling a build."""

import hashlib
import json
import os
import re
import stat
import subprocess


class ObservationUnavailable(Exception):
    """An observation could not be obtained; other observations can continue."""


class Report:
    def __init__(self):
        self.rows = []

    def add(self, item, requirement, observed=None, unavailable_reason=None):
        self.rows.append({
            "item": str(item),
            "requirement": requirement,
            "observed": observed,
            "unavailable_reason": unavailable_reason,
        })

    def observe(self, item, requirement, reader, display=None):
        try:
            value = reader()
            self.add(item, requirement, display(value) if display else value)
            return value
        except (OSError, ValueError, RuntimeError, ObservationUnavailable) as error:
            self.add(item, requirement, unavailable_reason=f"{type(error).__name__}: {error}")
            return None

    def emit(self):
        print(json.dumps({"observations": self.rows}, ensure_ascii=False, indent=2, default=str))


def command_output(command, cwd=None):
    result = subprocess.run(
        command, cwd=cwd, env={**os.environ, "LC_ALL": "C"},
        capture_output=True, text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ObservationUnavailable(f"Command exit code {result.returncode}: {detail}")
    return result.stdout.strip()


def file_metadata(path):
    info = path.stat()
    kind = "regular file" if stat.S_ISREG(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "other"
    return {"path": str(path), "type": kind, "bytes": info.st_size, "mode": f"{stat.S_IMODE(info.st_mode):04o}"}


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
        else:
            match = re.fullmatch(r"# (CONFIG_[A-Za-z0-9_-]+) is not set", line)
            if match:
                values[match[1]] = "n"
    return values


def report_config(report, path, requirements):
    values = report.observe(
        f"Configuration source: {path}", "Readable configuration file",
        lambda: config_values(path),
        lambda data: {"path": str(path), "recorded_options": len(data)},
    )
    for key, requirement in requirements.items():
        reason = None
        observed = None
        if values is None:
            reason = "Configuration source could not be read; see its observation"
        elif key not in values:
            reason = "No entry for this option is recorded in this configuration file"
        else:
            observed = values[key]
        report.add(f"{path}: {key}", requirement, observed, reason)
    return values
