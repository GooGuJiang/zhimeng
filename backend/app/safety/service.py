"""Compatibility shim: the original stub module. Implementation lives in ``app.safety.engine``;
callers should import from the package root (``from app import safety``)."""
from app.safety.engine import CRISIS_MESSAGE, check_input, check_output, filter_chunk, policy  # noqa: F401
