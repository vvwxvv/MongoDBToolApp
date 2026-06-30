"""Exception hierarchy for the Mongo client layer.

Repositories raise these instead of leaking raw pymongo exceptions, so
calling application code (FastAPI handlers, workers, CLI scripts, etc.)
can catch one stable set of errors regardless of driver internals.
"""


class MongoLibError(Exception):
    """Base class for all errors raised by this library."""


class ConnectionNotInitializedError(MongoLibError):
    """Raised when DB access is attempted before the client is initialized."""


class DuplicateKeyException(MongoLibError):
    """Raised when an insert/update violates a unique index."""


class DocumentNotFoundException(MongoLibError):
    """Raised when an operation expected to find a document didn't."""


class InvalidObjectIdError(MongoLibError):
    """Raised when a string cannot be parsed as a valid ObjectId."""
