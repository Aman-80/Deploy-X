
"""
DeployX Universal Deployment Strategy Engine

Responsibilities:
- Interpret project detection results.
- Select a deployment strategy.
- Identify missing information and risks.
- Support web, API and hybrid applications.
- Return structured data for generator plugins.

This module does not generate or execute deployment configurations.
"""

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class DeploymentStrategy:
    strategy_id: str
    category: str
    runtime: str | None

    build_required: bool
    web_server_required: bool
    reverse_proxy_required: bool
    containerization_supported: bool

    has_web_interface: bool
    exposes_api: bool
    is_hybrid: bool

    existing_dockerfile: bool
    existing_compose: bool

    requires_manual_configuration: bool
    requires_review: bool

    confidence: str
    reasons: list[str]
    warnings: list[str]


class StrategyEngine:

    STRATEGIES = {
        "static": {
            "category": "static",
            "build_required": False,
            "web_server_required": True,
            "reverse_proxy_required": False,
            "containerization_supported": True,
        },
        "web_application": {
            "category": "web",
            "build_required": True,
            "web_server_required": True,
            "reverse_proxy_required": True,
            "containerization_supported": True,
        },
        "api_service": {
            "category": "api",
            "build_required": True,
            "web_server_required": False,
            "reverse_proxy_required": True,
            "containerization_supported": True,
        },
        "background_worker": {
            "category": "worker",
            "build_required": True,
            "web_server_required": False,
            "reverse_proxy_required": False,
            "containerization_supported": True,
        },
        "desktop_application": {
            "category": "desktop",
            "build_required": True,
            "web_server_required": False,
            "reverse_proxy_required": False,
            "containerization_supported": False,
        },
        "custom": {
            "category": "custom",
            "build_required": False,
            "web_server_required": False,
            "reverse_proxy_required": False,
            "containerization_supported": False,
        },
    }

    VALID_CONFIDENCE = {"high", "medium", "low"}

    def analyze(self, detection: dict[str, Any]) -> DeploymentStrategy:

        if not isinstance(detection, dict):
            raise ValueError(
                "Detection result must be a dictionary."
            )

        project_type = str(
            detection.get("project_type", "unknown")
        ).lower()

        language = str(
            detection.get("language", "unknown")
        )

        detected_files = detection.get("detected_files", [])
        recommendations = detection.get("recommendations", [])

        if not isinstance(detected_files, list):
            detected_files = []

        if not isinstance(recommendations, list):
            recommendations = []

        # Normalize detected paths.
        normalized_files = {
            str(item).replace("\\", "/").lower().strip("/")
            for item in detected_files
            if isinstance(item, str)
        }

        file_names = {
            item.rsplit("/", 1)[-1]
            for item in normalized_files
        }

        # Existing deployment configurations are evidence only.
        existing_docker = "dockerfile" in file_names

        compose_names = {
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }

        existing_compose = bool(
            file_names.intersection(compose_names)
        )

        reasons = []
        warnings = []

        if existing_docker:
            reasons.append(
                "Existing Dockerfile detected."
            )

        if existing_compose:
            reasons.append(
                "Existing Docker Compose configuration detected."
            )

        # Read application classification.
        explicit_type = detection.get("application_type")

        valid_types = {
            "static",
            "web_application",
            "api_service",
            "background_worker",
            "desktop_application",
        }

        if not isinstance(explicit_type, str):
            explicit_type = None

        if explicit_type not in valid_types:
            explicit_type = None

        is_web = detection.get("is_web") is True
        is_api = detection.get("is_api") is True
        is_worker = detection.get("is_worker") is True
        is_desktop = detection.get("is_desktop") is True

        is_hybrid = is_web and is_api

        # Determine strategy.
        # Desktop applications take priority over other classifications.
        if is_desktop or explicit_type == "desktop_application":
            strategy_id = "desktop_application"
            reasons.append(
                "Desktop application indicators detected."
            )

        elif project_type == "static" or explicit_type == "static":
            strategy_id = "static"
            is_web = True
            reasons.append(
                "Static website indicators detected."
            )

        elif is_hybrid:
            strategy_id = "web_application"
            reasons.append(
                "Both web interface and API capabilities detected."
            )

        elif explicit_type == "web_application":
            strategy_id = "web_application"
            is_web = True
            reasons.append(
                "Web application classification supplied by analyzer."
            )

        elif explicit_type == "api_service":
            strategy_id = "api_service"
            is_api = True
            reasons.append(
                "API service classification supplied by analyzer."
            )

        elif explicit_type == "background_worker":
            strategy_id = "background_worker"
            is_worker = True
            reasons.append(
                "Background worker classification supplied by analyzer."
            )

        elif is_worker:
            strategy_id = "background_worker"
            reasons.append(
                "Background worker indicators detected."
            )

        elif is_api:
            strategy_id = "api_service"
            reasons.append(
                "API service indicators detected."
            )

        elif is_web:
            strategy_id = "web_application"
            reasons.append(
                "Web application indicators detected."
            )

        else:
            strategy_id = "custom"
            warnings.append(
                "Application purpose could not be determined reliably."
            )

        template = self.STRATEGIES[strategy_id]

        # Normalize confidence.
        confidence = str(
            detection.get("confidence", "low")
        ).lower()

        if confidence not in self.VALID_CONFIDENCE:
            confidence = "low"

        if strategy_id == "custom":
            confidence = "low"

        # Strategy-specific warnings.
        if strategy_id == "desktop_application":
            warnings.append(
                "Desktop applications require a dedicated runtime "
                "or GUI deployment strategy."
            )

        if strategy_id == "background_worker":
            warnings.append(
                "A background worker may require a queue, scheduler "
                "or external service."
            )

        if strategy_id == "custom":
            warnings.append(
                "A compatible generator plugin or manual configuration "
                "is required."
            )

        if not existing_docker:
            reasons.append(
                "No existing Dockerfile detected; generation may be required."
            )

        if not detected_files:
            warnings.append(
                "The analyzer did not provide a detected file list."
            )

        # Recommendations are warnings, not execution instructions.
        for recommendation in recommendations:
            warnings.append(str(recommendation))

        # Manual configuration is different from user review.
        requires_manual = (
            strategy_id in {
                "custom",
                "desktop_application",
            }
            or confidence == "low"
        )

        # Every generated deployment configuration must be reviewed.
        requires_review = True

        if existing_docker or existing_compose:
            warnings.append(
                "Existing deployment files must be reviewed before reuse."
            )

        return DeploymentStrategy(
            strategy_id=strategy_id,
            category=template["category"],
            runtime=(
                language
                if language.lower() != "unknown"
                else None
            ),

            build_required=template["build_required"],
            web_server_required=template["web_server_required"],
            reverse_proxy_required=template["reverse_proxy_required"],
            containerization_supported=(
                template["containerization_supported"]
            ),

            has_web_interface=is_web,
            exposes_api=is_api,
            is_hybrid=is_hybrid,

            existing_dockerfile=existing_docker,
            existing_compose=existing_compose,

            requires_manual_configuration=requires_manual,
            requires_review=requires_review,

            confidence=confidence,
            reasons=reasons,
            warnings=list(dict.fromkeys(warnings)),
        )


def select_strategy(detection: dict[str, Any]) -> dict:
    engine = StrategyEngine()
    strategy = engine.analyze(detection)

    return asdict(strategy)
