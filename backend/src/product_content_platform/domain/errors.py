class DomainValidationError(ValueError):
    """Raised when a command would create an invalid domain object."""


class EntityNotFoundError(LookupError):
    """Raised when a requested aggregate does not exist."""
