class DropError(Exception):
    pass


class DropNotFoundError(DropError):
    pass


class DropNotAvailableError(DropError):
    pass


class DropExpiredError(DropNotAvailableError):
    pass


class DropConsumedError(DropNotAvailableError):
    pass


class DropNotReadyError(DropNotAvailableError):
    pass


class FileTooLargeError(DropError):
    pass


class RateLimitExceededError(DropError):
    def __init__(self, *, retry_after: int) -> None:
        self.retry_after = max(retry_after, 0)
        super().__init__("Rate limit exceeded")
