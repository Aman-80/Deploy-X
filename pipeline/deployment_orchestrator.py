
"""
DeployX Universal Deployment Orchestrator

Coordinates:
1. Project detection
2. Deployment strategy selection
3. Generator plugin selection
4. Artifact validation

Does not execute application code or deploy containers.
"""

from pathlib import Path

try:
    # Package imports
    from .detect_project import detect_project
    from .strategy_engine import select_strategy
    from .generator_registry import GeneratorRegistry
    from .plugin_loader import PluginLoader
    from .config_validator import validate_artifacts

except ImportError:
    # Direct script imports
    from detect_project import detect_project
    from strategy_engine import select_strategy
    from generator_registry import GeneratorRegistry
    from config_validator import validate_artifacts


class DeploymentOrchestrator:

    def __init__(self, registry=None):
        self.registry = registry if registry is not None else GeneratorRegistry()

        self.plugin_loader = PluginLoader(self.registry)
        self.plugin_load_result = self.plugin_loader.load_plugins()

    def analyze_project(self, project_path):

        root = Path(project_path).resolve()

        if not root.is_dir():
            raise ValueError("Project directory does not exist.")

        detection = detect_project(str(root))

        if not isinstance(detection, dict):
            raise ValueError("Project analyzer returned an invalid result.")

        strategy = select_strategy(detection)

        if not isinstance(strategy, dict):
            raise ValueError("Strategy engine returned an invalid result.")

        plugin = self.registry.get_plugin(strategy["strategy_id"])

        return {
            "status": "analyzed",
            "project_path": str(root),
            "detection": detection,
            "strategy": strategy,
            "generator_available": plugin is not None,
            "requires_review": True,
        }

    def generate_deployment(self, project_path, output_path):

        analysis = self.analyze_project(project_path)

        source_root = Path(analysis["project_path"])
        output_root = Path(output_path).resolve()

        # Generated artifacts must remain separate from source code.
        if (
            output_root == source_root
            or source_root in output_root.parents
            or output_root in source_root.parents
        ):
            return {
                "status": "invalid_output_path",
                "analysis": analysis,
                "message": (
                    "Generated output must be stored in a separate "
                    "directory outside the source project."
                ),
            }

        strategy = analysis["strategy"]

        if strategy["requires_manual_configuration"]:
            return {
                "status": "review_required",
                "analysis": analysis,
                "message": (
                    "Project requires manual configuration "
                    "before automatic generation."
                ),
            }

        if not analysis["generator_available"]:
            return {
                "status": "unsupported",
                "analysis": analysis,
                "message": (
                    "No generator plugin is registered for this strategy."
                ),
            }

        generation = self.registry.generate(
            strategy_id=strategy["strategy_id"],
            project_path=str(source_root),
            output_path=str(output_root),
            detection=analysis["detection"],
            strategy=strategy,
        )

        if not isinstance(generation, dict):
            return {
                "status": "failed",
                "analysis": analysis,
                "message": "Generator returned an invalid response.",
            }

        if generation.get("status") != "success":
            return {
                "status": generation.get("status", "failed"),
                "analysis": analysis,
                "generation": generation,
                "requires_review": True,
            }

        validation = validate_artifacts(
            str(output_root),
            generation.get("generated_files", []),
        )

        return {
            "status": (
                "success" if validation["valid"] else "validation_failed"
            ),
            "analysis": analysis,
            "generation": generation,
            "validation": validation,
            "requires_review": True,
        }
