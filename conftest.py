"""Repository-root pytest configuration.

The accounting plugin is registered here because pytest only honours
``pytest_plugins`` in the rootdir conftest.  It records what the suite
collected, what it executed, and why anything was not executed; the report
is written only when ``FINSIGHT_TEST_ACCOUNTING_REPORT`` names a path, so
ordinary runs are unaffected.
"""

pytest_plugins = ["tests.accounting_plugin"]
