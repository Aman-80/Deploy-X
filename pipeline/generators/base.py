
"""
DeployX Universal Generator Plugin Interface

Defines the contract that every deployment generator
must follow, regardless of programming language or framework.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseGenerator(ABC):
    """
    Base class for all DeployX generator plugins.

    Each generator must:
    - Have a unique plugin_id.
    - Declare supported deployment strategies.
    - Implement the generate() method.
    """

    plugin_id: str = ""
    supported_strategies: set[str] = set()

    @abstractmethod
    def generate(
        self,
        project_path: str,
        output_path: str,
        detection: dict[str, Any],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Generate deployment artifacts.

        This method must not execute application code,
        build containers, or deploy applications.
        """
        raise NotImplementedError

    @staticmethod
    def validate_paths(
        project_path: str,
        output_path: str,
    ) -> tuple[Path, Path]:
        """
        Resolve and validate source and output directories.
        Generated output must remain separate from source.
        """

        source = Path(project_path).resolve()
        output = Path(output_path).resolve()

        if not source.is_dir():
            raise ValueError("Source project directory does not exist.")

        if (
            output == source
            or source in output.parents
            or output in source.parents
        ):
            raise ValueError(
                "Output directory must be separate from the source project."
            )

        return source, output
