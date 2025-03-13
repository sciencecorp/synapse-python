import datetime
from rich import filesize
from typing import Optional

__all__ = [
    "format_mode",
    "format_time",
    "filesize_binary",
]


def format_mode(mode):
    """
    Format file mode into rwx format
    Args:
        mode: File mode integer
    Returns:
        str: Formatted mode string (e.g., 'drwxr-xr--')
    """
    if mode is None:
        return "----------"

    result = ""
    # File type
    if mode & 0o40000:  # directory
        result += "d"
    elif mode & 0o120000:  # symlink
        result += "l"
    else:
        result += "-"

    # User permissions
    result += "r" if mode & 0o400 else "-"
    result += "w" if mode & 0o200 else "-"
    result += "x" if mode & 0o100 else "-"
    # Group permissions
    result += "r" if mode & 0o40 else "-"
    result += "w" if mode & 0o20 else "-"
    result += "x" if mode & 0o10 else "-"
    # Other permissions
    result += "r" if mode & 0o4 else "-"
    result += "w" if mode & 0o2 else "-"
    result += "x" if mode & 0o1 else "-"

    return result


def filesize_binary(
    size: int,
    *,
    precision: Optional[int] = 1,
    separator: Optional[str] = " ",
) -> str:
    """Convert a filesize in to a string (powers of 1024).
    Based off of rich.filesize.decimal() but for binary units.

    In this convention, ``1024 B = 1 kB``.

    Arguments:
        int (size): A file size.
        int (precision): The number of decimal places to include (default = 1).
        str (separator): The string to separate the value from the units (default = " ").

    Returns:
        `str`: A string containing a abbreviated file size and units.

    """
    return filesize._to_str(
        size,
        ("kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"),
        1024,
        precision=precision,
        separator=separator,
    )


def format_time(mtime: Optional[int]) -> str:
    """
    Format modification time

    Args:
        mtime: Modification time as seconds since epoch

    Returns:
        str: Formatted date string
    """

    if mtime is None:
        return " " * 12

    dt = datetime.datetime.fromtimestamp(mtime)
    now = datetime.datetime.now()

    # Use different format if file is from current year or not
    if dt.year == now.year:
        return dt.strftime("%b %d %H:%M")
    else:
        return dt.strftime("%b %d  %Y")
