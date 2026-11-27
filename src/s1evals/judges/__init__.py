"""Judges: Jev on the slice (fast), Claude on the slice, and a Claude agent on the full trace (slow)."""


class JudgeError(RuntimeError):
    """A judge call failed. Callers surface it; it is never read as an answer."""
