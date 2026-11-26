"""Typed service errors. Routes map ``status_code`` to HTTP; chat reports ``str(err)``."""

from __future__ import annotations


class ServiceError(Exception):
    status_code: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.detail = message


class InvalidTickerError(ServiceError):
    status_code = 422


class UnknownTickerError(ServiceError):
    status_code = 404


class NotInWatchlistError(ServiceError):
    status_code = 404


class AlreadyInWatchlistError(ServiceError):
    status_code = 409
