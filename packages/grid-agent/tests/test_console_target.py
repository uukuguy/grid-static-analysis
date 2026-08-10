from importlib import import_module


def test_console_target_imports_and_calls_successfully() -> None:
    module = import_module("grid_agent.cli.app")
    assert module.main() == 0
