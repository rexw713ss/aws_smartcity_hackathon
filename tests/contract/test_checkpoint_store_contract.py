"""CheckpointStore contract.

Feature: aws-stage1-foundation. Property 11 (round-trip and missing-key nullity).
"""

from datetime import UTC, datetime

from youth_compass.ports import CheckpointStore, WorkflowCheckpoint


def _checkpoint(node: str) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        workflow_id="wf-1",
        node=node,
        state={"step": node},
        saved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


class TestCheckpointStoreContract:
    def test_property_11_save_then_load_round_trip(self, checkpoint_store: CheckpointStore) -> None:
        checkpoint = _checkpoint("profile")
        checkpoint_store.save("wf-1", checkpoint)
        assert checkpoint_store.load("wf-1") == checkpoint

    def test_property_11_load_of_unknown_id_returns_none(
        self, checkpoint_store: CheckpointStore
    ) -> None:
        assert checkpoint_store.load("never-saved") is None

    def test_save_twice_keeps_the_later_checkpoint(self, checkpoint_store: CheckpointStore) -> None:
        checkpoint_store.save("wf-1", _checkpoint("profile"))
        checkpoint_store.save("wf-1", _checkpoint("validate"))
        loaded = checkpoint_store.load("wf-1")
        assert loaded is not None
        assert loaded.node == "validate"
