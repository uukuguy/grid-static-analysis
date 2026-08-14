from importlib import import_module

import grid_simulator


def test_package_version() -> None:
    assert grid_simulator.__version__ == "0.2.0"


def test_console_target_imports_successfully() -> None:
    module = import_module("grid_simulator.cli")
    assert callable(module.main)
