"""
Shared utilities for the tracker app.
"""


def safe_content_disposition_filename(name):
    """
    Sanitize a string for use in a Content-Disposition filename attribute
    to prevent header injection (e.g. newlines, double-quotes).
    Keeps only alphanumeric, space, hyphen, underscore.
    """
    if not name or not isinstance(name, str):
        return "download"
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    return safe.strip() or "download"
