
from ..generate_configs import generate_configs
from .base import BaseGenerator


class ConfigBundleGenerator(BaseGenerator):

    plugin_id = "config_bundle"

    supported_strategies = {
        "web_application",
        "api_service",
        "static",
    }

    def generate(
        self,
        project_path: str,
        output_path: str,
        detection: dict,
        strategy: dict,
    ) -> dict:

        return generate_configs(
            project_path=project_path,
            output_path=output_path,
            detection=detection,
        )


def create_plugin():
    return ConfigBundleGenerator()
