from scripts.deploy_site import _api_v1_base


def test_api_v1_base_appends_versioned_path() -> None:
    assert _api_v1_base("https://example.lambda-url.us-east-1.on.aws/") == (
        "https://example.lambda-url.us-east-1.on.aws/api/v1"
    )


def test_api_v1_base_does_not_duplicate_versioned_path() -> None:
    assert _api_v1_base("https://example.test/api/v1/") == "https://example.test/api/v1"
