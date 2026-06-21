"""Project exceptions."""


class AssemblyError(Exception):
    """Base assembly error. handler indicates which error handler should respond."""
    def __init__(self, message, handler=None, payload=None):
        super().__init__(message)
        self.handler = handler  # 1, 2, or 3
        self.payload = payload or {}


# ---------- ffmpeg / ffprobe lookup ----------
