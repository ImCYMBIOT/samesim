"""
PluginLoader — resolves, validates, and instantiates plugin classes.

Plugins are referenced by fully-qualified class path in config files:
    "samesim.plugins.communication.gossip.GossipProtocol"

The loader:
    1. Imports the module
    2. Resolves the class
    3. Validates it is a concrete subclass of the expected port ABC
    4. Instantiates it with no constructor arguments

Plugins must have a zero-argument __init__. Configuration is passed
to their initialize() methods by ExperimentRunner after instantiation.

This keeps plugin discovery explicit (no magic entry-points) and
reproducible (same config → same plugin instance).
"""
from __future__ import annotations

import importlib
from typing import Any, Type, TypeVar

T = TypeVar("T")


class PluginLoadError(Exception):
    """Raised when a plugin cannot be loaded, validated, or instantiated."""


class PluginLoader:
    """Resolves dotted class paths to validated, instantiated port implementations.

    Usage:
        loader = PluginLoader()
        behavior = loader.load(
            "samesim.plugins.behaviors.gossip_behavior.GossipBehavior",
            BehaviorPort,
            config={},
        )
    """

    def load(
        self,
        class_path: str,
        expected_base: Type[T],
        config: dict[str, Any] | None = None,
    ) -> T:
        """Load a plugin by dotted class path and validate it implements expected_base.

        Args:
            class_path:    Fully-qualified class path, e.g. "my.module.MyClass".
            expected_base: The port ABC the class must implement.
            config:        Unused in this call; reserved for future constructor injection.

        Returns:
            A zero-argument-constructed instance of the plugin class.

        Raises:
            PluginLoadError: If the module cannot be imported, the class is not
                             found, or it does not implement expected_base.
        """
        if "." not in class_path:
            raise PluginLoadError(
                f"Invalid class path '{class_path}'. "
                f"Expected format: 'module.path.ClassName'"
            )

        module_path, class_name = class_path.rsplit(".", 1)

        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise PluginLoadError(
                f"Cannot import module '{module_path}' "
                f"(from class path '{class_path}'): {exc}"
            ) from exc

        cls = getattr(module, class_name, None)
        if cls is None:
            raise PluginLoadError(
                f"Class '{class_name}' not found in module '{module_path}'."
            )

        if not (isinstance(cls, type) and issubclass(cls, expected_base)):
            raise PluginLoadError(
                f"'{class_path}' must be a subclass of "
                f"{expected_base.__name__}, but got {cls!r}."
            )

        if cls is expected_base:
            raise PluginLoadError(
                f"Cannot instantiate the abstract base class {expected_base.__name__} directly. "
                f"Provide a concrete implementation."
            )

        try:
            instance: T = cls()
        except Exception as exc:
            raise PluginLoadError(
                f"Failed to instantiate '{class_path}': {exc}"
            ) from exc

        return instance
