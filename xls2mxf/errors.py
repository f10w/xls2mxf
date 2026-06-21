"""Исключения проекта."""


class AssemblyError(Exception):
    """Базовая ошибка сборки. handler — какой обработчик должен сработать."""
    def __init__(self, message, handler=None, payload=None):
        super().__init__(message)
        self.handler = handler          # 1, 2 или 3
        self.payload = payload or {}


# ---------- поиск ffmpeg / ffprobe ----------
