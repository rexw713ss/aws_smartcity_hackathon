"""Controlled external-source discovery and acquisition."""

from youth_compass.acquisition.contracts import AcquisitionStart
from youth_compass.acquisition.service import DataAcquisitionService, IngestionSubmitter
from youth_compass.ports.source_connector import AcquiredSource, DataRequirement, SourceCandidate

__all__ = [
    "AcquiredSource",
    "AcquisitionStart",
    "DataAcquisitionService",
    "DataRequirement",
    "IngestionSubmitter",
    "SourceCandidate",
]
