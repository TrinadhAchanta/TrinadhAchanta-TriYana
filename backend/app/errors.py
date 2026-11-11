"""Domain errors mapped to HTTP responses by the API layer."""


class DomainError(Exception):
    status_code = 400

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    status_code = 403


class Conflict(DomainError):
    status_code = 409


class Unprocessable(DomainError):
    status_code = 422


class PaymentDeclined(DomainError):
    status_code = 402
