"""In-memory ConversationContextStore binding for the contract suite."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from tests.contract.registry import register_conversation_store
from youth_compass.agent import ConversationContextStore, InMemoryConversationContextStore


@register_conversation_store("memory")
@contextmanager
def _memory_conversation_store() -> Iterator[ConversationContextStore]:
    yield InMemoryConversationContextStore(ttl=timedelta(minutes=30))
