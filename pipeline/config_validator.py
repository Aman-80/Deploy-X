
"""
DeployX Configuration Validator

Performs safe, generic validation of generated deployment artifacts.
Does not execute project code or shell commands.
"""

from pathlib import Path


class ConfigValidator:

    def validate(self, output_path, generated_files):

        output = Path(output_path).resolve()

        result = {
            "status": "passed",
            "valid": True,
            "checked_files": [],
            "errors": [],
            "warnings": [],
        }

        if not output.exists() or not output.is_dir():
            result["status"] = "failed"
            result["valid"] = False
            result["errors"].append(
                "Generated output directory does not exist."
            )
            return result

        if not isinstance(generated_files, list):
            result["status"] = "failed"
            result["valid"] = False
            result["errors"].append(
                "Generated files must be provided as a list."
            )
            return result

        if not generated_files:
            result["status"] = "failed"
            result["valid"] = False
            result["errors"].append(
                "No generated artifacts were provided."
            )
            return result

        for filename in generated_files:

            if not isinstance(filename, str) or not filename.strip():
                result["errors"].append(
                    "Invalid generated artifact name."
                )
                continue

            if Path(filename).is_absolute():
                result["errors"].append(
                    f"Absolute artifact path rejected: {filename}"
                )
                continue

            candidate = output / filename

            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(output)
            except (ValueError, OSError, RuntimeError):
                result["errors"].append(
                    f"Missing or unsafe artifact: {filename}"
                )
                continue

            if candidate.is_symlink():
                result["errors"].append(
                    f"Symbolic link artifact rejected: {filename}"
                )
                continue

            if not resolved.is_file() and not resolved.is_dir():
                result["errors"].append(
                    f"Unsupported artifact type: {filename}"
                )
                continue

            if resolved.is_file() and resolved.stat().st_size == 0:
                result["warnings"].append(
                    f"Artifact is empty: {filename}"
                )

            result["checked_files"].append(filename)

        if result["errors"]:
            result["status"] = "failed"
            result["valid"] = False

        return result


def validate_artifacts(output_path, generated_files):

    validator = ConfigValidator()

    return validator.validate(
        output_path,
        generated_files
    )
