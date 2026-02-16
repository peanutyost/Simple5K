"""
Server-side validators for tracker app (e.g. image upload content validation).
"""

# Magic bytes for allowed image types (first 12 bytes sufficient for detection)
_IMAGE_SIGNATURES = [
    (b'\xff\xd8\xff', 'JPEG'),
    (b'\x89PNG\r\n\x1a\n', 'PNG'),
    (b'GIF87a', 'GIF'),
    (b'GIF89a', 'GIF'),
    (b'RIFF', 'WEBP'),  # WebP: RIFF....WEBP at offset 8
]


def validate_image_file(uploaded_file, max_size_mb=10):
    """
    Validate that an uploaded file is a real image by checking magic bytes.
    Raises django.core.exceptions.ValidationError if invalid.
    Optional max_size_mb caps file size (default 10 MB).
    """
    from django.core.exceptions import ValidationError

    if not uploaded_file:
        return
    if not hasattr(uploaded_file, 'read'):
        raise ValidationError('Invalid file upload.')
    max_bytes = max_size_mb * 1024 * 1024
    if uploaded_file.size and uploaded_file.size > max_bytes:
        raise ValidationError(f'File size must not exceed {max_size_mb} MB.')

    raw = uploaded_file.read(12)
    uploaded_file.seek(0)
    if len(raw) < 6:
        raise ValidationError('File is too small or empty to be a valid image.')

    if raw[:3] == b'\xff\xd8\xff':
        return
    if raw[:8] == b'\x89PNG\r\n\x1a\n':
        return
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        return
    if raw[:4] == b'RIFF' and len(raw) >= 12 and raw[8:12] == b'WEBP':
        return

    raise ValidationError(
        'Uploaded file does not appear to be a valid image (JPEG, PNG, GIF, or WebP).'
    )
