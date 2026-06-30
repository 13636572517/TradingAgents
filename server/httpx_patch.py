# Patch for httpx to handle non-ASCII header values gracefully
# This file should be imported early in the application startup

import httpx._models as _httpx_models

# Store original function
_original_normalize = _httpx_models._normalize_header_value

def _patched_normalize_header_value(value, encoding=None):
    """Patch httpx header normalization to handle non-ASCII gracefully."""
    if isinstance(value, str):
        try:
            # Try ASCII first (HTTP/1.1 spec)
            return value.encode(encoding or "ascii")
        except UnicodeEncodeError:
            # Fallback: strip non-ASCII characters
            import logging
            logging.getLogger(__name__).warning(
                "Stripping non-ASCII characters from HTTP header value: %r", 
                value[:50]
            )
            return value.encode("ascii", "ignore")
    # Fallback to original for non-string types
    return _original_normalize(value, encoding)

# Apply patch
_httpx_models._normalize_header_value = _patched_normalize_header_value
