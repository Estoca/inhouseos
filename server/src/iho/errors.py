from __future__ import annotations


class IhoError(Exception):
    """An error the caller can act on: an HTTP status, a stable code and a sentence for the agent."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def as_json(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}
