import pytest
from unittest.mock import MagicMock
from crew_agent.core.ui import TerminalUI

@pytest.fixture
def mock_ui():
    ui = MagicMock(spec=TerminalUI)
    ui.console = MagicMock()
    return ui

@pytest.fixture
def mock_config():
    from crew_agent.core.models import AppConfig
    return AppConfig(model="mock-model", base_url="http://mock")
