"""AWS endpoint abstraction for MiniStack/LocalStack contract testing."""

from shared.aws.config import AwsSettings, get_aws_settings

__all__ = ["AwsSettings", "get_aws_settings"]
