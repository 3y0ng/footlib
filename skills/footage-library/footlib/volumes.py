"""Which drive a file lives on, so the library knows what to plug in."""
import os
import plistlib
import subprocess
from functools import lru_cache


def mount_point(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.ismount(p):
        p = os.path.dirname(p)
    return p


@lru_cache(maxsize=None)
def volume_info(mount: str) -> tuple[str, str]:
    """(uuid, name) for a mount point. Falls back to the mount path if diskutil fails."""
    try:
        out = subprocess.run(["diskutil", "info", "-plist", mount], capture_output=True, check=True).stdout
        info = plistlib.loads(out)
        return info.get("VolumeUUID") or mount, info.get("VolumeName") or os.path.basename(mount) or "/"
    except Exception:
        return mount, os.path.basename(mount) or "/"


def for_path(path: str) -> tuple[str, str, str]:
    m = mount_point(path)
    uuid, name = volume_info(m)
    return uuid, name, m
