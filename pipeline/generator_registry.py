
"""
DeployX Generator Registry

Registers deployment generator plugins and selects
the appropriate plugin based on the deployment strategy.
"""

from typing import Any, Protocol


class GeneratorPlugin(Protocol):

    plugin_id: str
    supported_strategies: set[str]

    def generate(
        self,
        project_path: str,
        output_path: str,
        detection: dict[str, Any],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class GeneratorRegistry:

    def __init__(self):
        self._plugins = {}

    def register(self, plugin: GeneratorPlugin):

        plugin_id = getattr(plugin, "plugin_id", None)
        strategies = getattr(plugin, "supported_strategies", None)

        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ValueError("Plugin must have a valid plugin_id.")

        if not isinstance(strategies, set) or not strategies:
            raise ValueError(
                "Plugin must declare supported strategies."
            )

        if plugin_id in self._plugins:
            raise ValueError(
                f"Generator plugin already registered: {plugin_id}"
            )

        self._plugins[plugin_id] = plugin

    def unregister(self, plugin_id: str):

        if plugin_id not in self._plugins:
            raise KeyError(f"Unknown generator plugin: {plugin_id}")

        del self._plugins[plugin_id]

    def get_plugin(self, strategy_id: str):

        matches = [
            plugin
            for plugin in self._plugins.values()
            if strategy_id in plugin.supported_strategies
        ]

        if not matches:
            return None

        if len(matches) > 1:
            raise RuntimeError(
                f"Multiple plugins support strategy: {strategy_id}"
            )

        return matches[0]

    def list_plugins(self):

        return [
            {
                "plugin_id": plugin.plugin_id,
                "supported_strategies": sorted(
                    plugin.supported_strategies
                ),
            }
            for plugin in self._plugins.values()
        ]

    def generate(
        self,
        strategy_id: str,
        project_path: str,
        output_path: str,
        detection: dict[str, Any],
        strategy: dict[str, Any],
    ):

        plugin = self.get_plugin(strategy_id)

        if plugin is None:
            return {
                "status": "unsupported",
                "strategy": strategy_id,
                "message": "No generator plugin is registered for this strategy.",
            }

        return plugin.generate(
            project_path=project_path,
            output_path=output_path,
            detection=detection,
            strategy=strategy,
        )
