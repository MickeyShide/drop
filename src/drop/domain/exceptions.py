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
    pass


