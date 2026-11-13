"""API errors in the contract shape {"error": {"code", "message"}}.

Raise ApiError anywhere in a request; app.main turns it into the JSON body.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_found(message: str, code: str = "NOT_FOUND") -> ApiError:
    return ApiError(404, code, message)


def conflict(message: str, code: str = "CONFLICT") -> ApiError:
    return ApiError(409, code, message)


def invalid(message: str, code: str = "INVALID_INPUT") -> ApiError:
    return ApiError(422, code, message)


def unavailable(message: str, code: str = "DATA_UNAVAILABLE") -> ApiError:
    return ApiError(503, code, message)
