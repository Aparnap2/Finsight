"""Test-only AWS endpoint configuration for MiniStack contract testing.

Single source of truth for ``AWS_ENDPOINT_URL`` selection:

- Host (outside Docker): ``http://localhost:4566``
- Container (inside compose network): ``http://ministack:4566``

Do not scatter these literals through tests. Test credentials are ``test``/``test``
in ``us-east-1`` — never real credentials. ``AWS_ENDPOINT_URL`` is read from
the environment; when unset, the host default is used. When running inside
Docker, set ``AWS_ENDPOINT_URL=http://ministack:4566`` (see
``docker-compose.ministack.yml``).

Tenant isolation note (P5-03 #5, #9): buckets are per-deployment
(``finsight-evidence-test`` etc., not per-tenant). Isolation is via key prefix
``{tenant_id}/...`` enforced in ``finance/object_store`` before any network
call — this module only provides the endpoint/bucket config, never tenant
selection. Cross-tenant attempts raise ``TenantIsolationError`` uniformly.

This module has no dependency on ``boto3`` and is safe to import in unit tests
without Docker or network.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AwsSettings(BaseSettings):
    """Test-only AWS endpoint and credential envelope.

    All fields are ``TEST-ONLY`` and carry no real secrets.
    Production code must use real AWS env/instance-role credentials
    outside this module; this envelope is never used in production.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Endpoint selection — host default, container override via env
    aws_endpoint_url: str = Field(
        default="http://localhost:4566",
        description="MiniStack endpoint. Host: http://localhost:4566, container: http://ministack:4566",
    )
    aws_region: str = Field(default="us-east-1")
    aws_access_key_id: str = Field(default="test")
    aws_secret_access_key: str = Field(default="test")

    # Bucket naming — test-only, deterministic
    s3_evidence_bucket: str = Field(default="finsight-evidence-test")
    s3_legacy_outbound_bucket: str = Field(default="finsight-legacy-outbound-test")
    s3_legacy_result_bucket: str = Field(default="finsight-legacy-result-test")

    @property
    def is_ministack(self) -> bool:
        """Return True when pointing at a MiniStack/LocalStack endpoint."""
        url = self.aws_endpoint_url.lower()
        return "4566" in url or "localstack" in url or "ministack" in url

    def container_endpoint(self) -> str:
        """Return the in-compose-network endpoint for container usage."""
        # If the host endpoint already points at localhost, the container peer is ministack
        if "localhost" in self.aws_endpoint_url:
            return self.aws_endpoint_url.replace("localhost", "ministack")
        if "127.0.0.1" in self.aws_endpoint_url:
            return self.aws_endpoint_url.replace("127.0.0.1", "ministack")
        return self.aws_endpoint_url

    def host_endpoint(self) -> str:
        """Return the host endpoint for local (outside Docker) usage."""
        if "ministack" in self.aws_endpoint_url:
            return self.aws_endpoint_url.replace("ministack", "localhost")
        return self.aws_endpoint_url


@lru_cache
def get_aws_settings() -> AwsSettings:
    """Return cached test AWS settings (env-driven, reload)."""
    return AwsSettings()


def get_aws_endpoint_for_env() -> str:
    """Return the endpoint URL appropriate for the current environment.

    Inside Docker (``AWS_ENDPOINT_URL`` contains ``ministack``) the container
    value is used; otherwise the host value. Explicit ``AWS_ENDPOINT_URL`` env
    takes precedence verbatim.
    """
    explicit = os.getenv("AWS_ENDPOINT_URL")
    if explicit:
        return explicit
    settings = get_aws_settings()
    # Heuristic: if we are inside Docker, /proc/1/cgroup hints at container
    # but we keep it simple — honour localhost default and let compose override
    return settings.aws_endpoint_url
