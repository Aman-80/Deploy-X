
"""
DeployX Trusted Plugin Loader

Only explicitly approved built-in generator modules can be loaded.
Repositories being analyzed are never treated as plugin sources.
"""

import importlib
import re

try:
    from .generator_registry import GeneratorRegistry
    from .generators import BaseGenerator
except ImportError:
    from generator_registry import GeneratorRegistry
    from generators import BaseGenerator


class PluginLoader:

    # Only trusted, built-in plugin modules can be loaded.
    TRUSTED_PLUGINS = ("config_bundle",)

    MODULE_PATTERN = re.compile(
        r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    )

    def __init__(self, registry: GeneratorRegistry):
        if not isinstance(registry, GeneratorRegistry):
            raise TypeError("A valid GeneratorRegistry is required.")

        self.registry = registry

    def load_plugins(self):

        loaded = []
        errors = []

        for module_name in self.TRUSTED_PLUGINS:

            if (
                not isinstance(module_name, str)
                or not self.MODULE_PATTERN.fullmatch(module_name)
            ):
                errors.append("Rejected invalid plugin module name.")
                continue

            try:
                module = importlib.import_module(
                    f".generators.{module_name}",
                    package=__package__ or "pipeline"
                )

                plugin_factory = getattr(
                    module,
                    "create_plugin",
                    None
                )

                if not callable(plugin_factory):
                    raise ValueError(
                        "Plugin must provide create_plugin()."
                    )

                plugin = plugin_factory()

                if not isinstance(plugin, BaseGenerator):
                    raise TypeError(
                        "Plugin must inherit from BaseGenerator."
                    )

                self.registry.register(plugin)
                loaded.append(plugin.plugin_id)

            except Exception as exc:
                errors.append(
                    f"{module_name}: {type(exc).__name__}: {exc}"
                )

        return {
            "loaded": loaded,
            "errors": errors,
            "total_loaded": len(loaded),
            "total_errors": len(errors),
        }
