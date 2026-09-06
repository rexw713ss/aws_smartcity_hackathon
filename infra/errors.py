"""Infrastructure configuration errors.

Raised at CDK construction time, before any template is written, so a
misconfigured synth fails fast and leaves no partial output for a later deploy.
"""


class InfraConfigError(Exception):
    """A required CDK context value is missing, invalid, or empty."""
