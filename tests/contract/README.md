# Contract test suite

One reusable suite per Port. Any adapter — the in-memory reference, a Stage 2
local adapter, or a Stage 2 AWS adapter — is proven interchangeable by binding it
to the same suite. The suite runs with no AWS credentials and no cost; AWS-backed
adapters route every call through `moto`.

## Bind a new adapter in three steps

1. **Write and decorate the factory.** In your adapter package, write a
   zero-argument function returning a context manager that yields a fresh adapter
   instance, and decorate it with the Port's `register_*` from
   `tests/contract/registry.py`:

   ```python
   from contextlib import contextmanager
   from tests.contract.registry import register_object_store

   @register_object_store("s3-moto")
   @contextmanager
   def _s3_object_store():
       with mock_aws():
           yield S3ObjectStore(bucket="contract-test")
   ```

2. **Make the module import.** Import it from
   `tests/contract/reference/__init__.py` (for a reference adapter) or from an
   adapter-side conftest, so registration happens before collection.

3. **Run the suite for your adapter:**

   ```bash
   uv run pytest tests/contract -k "s3-moto"
   ```

The contract class body never changes. N registered factories produce N runs.

## Fixture and test class per Port

| Port | Fixture | Contract class |
|---|---|---|
| ObjectStore | `object_store` | `test_object_store_contract.py` |
| DataCatalog | `catalog` | `test_catalog_contract.py` |
| QueryEngine | `query_engine` | `test_query_engine_contract.py` |
| ModelProvider | `model_provider` | `test_model_provider_contract.py` |
| ForecastService | `forecast_service` | `test_forecast_service_contract.py` |
| WorkflowRunner | `workflow_runner` | `test_workflow_runner_contract.py` |
| CheckpointStore | `checkpoint_store` | `test_checkpoint_store_contract.py` |
| EventBus | `event_bus` | `test_event_bus_contract.py` |
| Clock | `clock` | `test_clock_contract.py` |
