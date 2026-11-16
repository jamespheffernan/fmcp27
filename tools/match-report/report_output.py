"""Publish only an immutable regular HTML original beneath Agent Outputs."""

import hashlib, os, re, stat, unicodedata
from pathlib import Path
from datetime import date as civil_date

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _name(value):
    clean = "".join(
        c if c.isalnum() or c in " -" else " "
        for c in unicodedata.normalize("NFC", value)
    )
    return " ".join(clean.split())[:65] or "Match"


def validate_filename(value):
    """Accept one bounded HTML leaf; the output directory is always fixed."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value.startswith(".")
        or not value.endswith(".html")
        or any(
            c in "/\\:" or unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp")
            for c in value
        )
        or len(value.encode("utf-8")) > 250
    ):
        raise ValueError("filename must be one safe HTML filename under Agent Outputs")
    return value


def publish(data, html, *, outputs=None, filename=None):
    if (
        not isinstance(html, bytes)
        or not html.startswith(b"<!doctype html>")
        or len(html) > 64 * 1024 * 1024
    ):
        raise ValueError("Invalid or oversized generated HTML")
    root = Path.home() / "Agent Outputs" if outputs is None else Path(outputs)
    if not root.is_absolute():
        raise ValueError("Output root must be absolute")
    digest = hashlib.sha256(html).hexdigest()
    teams = data["teams"]
    date = data["fixture"]["date"]
    if not isinstance(date, str) or civil_date.fromisoformat(date).isoformat() != date:
        raise ValueError("Invalid fixture date for output name")
    default_filename = f"{date} — {_name(teams[0]['short_name'])} v {_name(teams[1]['short_name'])} — interactive report {digest[:12]}.html"
    # Team names come from the checked source, but remain untrusted path text.
    if len(default_filename.encode()) > 250:
        default_filename = f"{date} — Interactive match report {digest[:16]}.html"
    filename = default_filename if filename is None else validate_filename(filename)
    parent = os.open("/", FLAGS)
    try:
        for index, part in enumerate(root.parts[1:]):
            if index == len(root.parts) - 2:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            child = os.open(part, FLAGS, dir_fd=parent)
            os.close(parent)
            parent = child
        reused = False
        try:
            fd = os.open(
                filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
        except FileExistsError:
            fd = os.open(
                filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size != len(html):
                    raise FileExistsError(
                        "Existing report filename is not the matching original"
                    )
                existing = b""
                while chunk := os.read(fd, 65536):
                    existing += chunk
                if hashlib.sha256(existing).hexdigest() != digest:
                    raise FileExistsError(
                        "Existing report content differs; no overwrite attempted"
                    )
                reused = True
            finally:
                os.close(fd)
        else:
            # A failure may leave a partial artifact. Never unlink this public
            # leaf during error cleanup: another actor can replace it at any
            # point, including between an identity check and unlink.
            with os.fdopen(fd, "wb") as f:
                f.write(html)
                f.flush()
                os.fsync(f.fileno())
                info = os.fstat(f.fileno())
        visible = os.stat(root / filename, follow_symlinks=False)
        relative = os.stat(filename, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(visible.st_mode)
            or (visible.st_dev, visible.st_ino) != (info.st_dev, info.st_ino)
            or (relative.st_dev, relative.st_ino) != (info.st_dev, info.st_ino)
        ):
            raise OSError("Output directory or report changed during publication")
    finally:
        os.close(parent)
    return {
        "path": str(root / filename),
        "bytes": len(html),
        "sha256": digest,
        "existing_matching_original": reused,
        "canonical_original": True,
        "game_writes": False,
        "game_inputs": False,
    }
