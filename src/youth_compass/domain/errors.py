"""Domain error hierarchy for failures that cross a port boundary.

Every adapter translates its technology-specific exceptions into one of these
types. ``botocore`` errors, ``OSError``, ``duckdb.Error``, and ``sqlite3.Error``
are adapter-internal and must never escape through a port: the contract test
suite fails an adapter that lets one propagate.

Filename sanctioned by docs/07-project-structure.md section 2, which already
lists ``domain/errors.py`` in the planned domain package. This module contains
exception classes only.
"""


class YouthCompassError(Exception):
    """Base for every error crossing a port boundary."""


class ObjectNotFoundError(YouthCompassError):
    """No object exists at the requested URI. Raised by ObjectStore.get."""


class ObjectStoreOperationError(YouthCompassError):
    """Object storage failed for a reason other than a missing object."""


class DatasetNotFoundError(YouthCompassError):
    """No dataset is registered under the requested identifier."""


class CatalogOperationError(YouthCompassError):
    """The dataset catalog could not complete an operation."""


class AnalyticsNotAvailableError(YouthCompassError):
    """No compatible published observation exists for an analytics request."""


class QueryNotPermittedError(YouthCompassError):
    """The query names a table, metric, or dimension outside the allowlist."""


class QueryExecutionError(YouthCompassError):
    """The query engine failed to execute an otherwise permitted query."""


class ModelInvocationError(YouthCompassError):
    """The model provider could not produce a response."""


class ForecastNotAvailableError(YouthCompassError):
    """No forecast artifact exists for the requested key."""


class TrainingRejectedError(YouthCompassError):
    """The training request was refused before a run was created."""


class WorkflowStateError(YouthCompassError):
    """The workflow is unknown, or already settled, for the requested action."""


class WorkflowNotFoundError(WorkflowStateError):
    """No durable workflow state exists for the requested identifier."""


class WorkflowPersistenceError(YouthCompassError):
    """Durable workflow state could not be saved or loaded."""


class SourceNormalizationError(YouthCompassError):
    """An uploaded source cannot be converted into a canonical tabular stream."""


class SourceAcquisitionError(YouthCompassError):
    """An external source could not be safely discovered or fetched."""


class ConversationPersistenceError(YouthCompassError):
    """Structured conversation context could not be saved or loaded.

    Never fatal to a turn: the question is answered without inherited scope.
    """


class ConfigurationError(YouthCompassError):
    """Configuration is invalid; provider selection failed validation."""
