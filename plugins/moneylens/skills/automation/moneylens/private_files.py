"""Private filesystem access on POSIX and Windows; no system credential store."""
import os
from pathlib import Path
import stat


def _windows():
    from .windows_access import WindowsAccess
    return WindowsAccess()


def regular(path, directory=False):
    info = Path(path).lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
            (not directory and info.st_nlink != 1)):
        raise ValueError('Private storage requires regular files, without links or reparse points')
    return info


def check_private(path, directory=False):
    info = regular(path, directory)
    if os.name == 'nt':
        _windows().check(Path(path))
    elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise ValueError('Private storage requires owner-only access')


def protect(path, directory=False):
    info = regular(path, directory)
    if os.name == 'nt':
        _windows().protect(Path(path), directory)
    else:
        if info.st_uid != os.getuid(): raise ValueError('Private storage requires current-user ownership')
        os.chmod(path, 0o700 if directory else 0o600)
    check_private(path, directory)


def open_private(path):
    """Verify identity and permissions again on the descriptor before reading."""
    check_private(path)
    before = Path(path).lstat()
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError('Private file changed while opening')
        check_private(path)
        return os.fdopen(fd, encoding='utf-8')
    except BaseException:
        os.close(fd)
        raise
