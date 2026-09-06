"""AWS adapter bindings for the contract-test suite.

Each module registers one adapter factory via ``register_*``, wrapping moto's
``mock_aws`` so the contract suite runs against a fake S3/Glue/etc. at zero cost.
"""
