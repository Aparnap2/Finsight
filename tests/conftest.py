import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# The accounting plugin is registered by the repository-root conftest.py
# (pytest only allows ``pytest_plugins`` in the rootdir conftest).
