"""
Encoding detection for text file handlers.

charset-normalizer ships transitively with requests, so this costs no new
dependency. Detection runs on a head sample only; anything ambiguous falls
back to UTF-8, which keeps the pre-detection behavior for the common case.
"""
import logging

logger = logging.getLogger(__name__)

SAMPLE_BYTES = 65536


def detect_encoding(sample: bytes) -> str:
    """Best-effort encoding from a byte sample.

    Deterministic ladder rather than pure statistics: BOMs, then strict
    UTF-8, then cp1252 (Western Europe's de-facto default, and unlike
    latin-1 it can actually fail so it carries signal), then
    charset-normalizer for everything else. Statistical detectors are
    unreliable on small samples — they happily pick exotic codepages for
    plain latin-1 — so they come last, and latin-1 (which never fails)
    is the terminal fallback.
    """
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith(b"\xff\xfe"):
        return "utf-16"
    if sample.startswith(b"\xfe\xff"):
        return "utf-16-be"

    for encoding in ("utf-8", "cp1252"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue

    try:
        from charset_normalizer import from_bytes

        best = from_bytes(sample).best()
        if best is not None and best.encoding:
            return best.encoding
    except Exception as exc:
        logger.debug("Encoding detection failed: %s", exc)
    return "latin-1"


def detect_stream_encoding(file_stream) -> str:
    """Detect from the head of a seekable binary stream, then rewind."""
    sample = file_stream.read(SAMPLE_BYTES)
    file_stream.seek(0)
    return detect_encoding(sample)
