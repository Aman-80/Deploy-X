
import json
import os
import re
import sys
import zipfile


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
}

PROJECT_PATH = os.environ.get(
    "PROJECT_PATH",
    "/workspace/Smart-Route-and-Data-Analyzer"
)
ARTIFACT_DIR = "/artifacts"


def build_project():
    root = os.path.realpath(PROJECT_PATH)

    if not os.path.isdir(root):
        raise ValueError("Repository directory not found.")

    repo_name = os.path.basename(root)

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repo_name):
        raise ValueError("Invalid repository directory name.")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    artifact_path = os.path.join(
        ARTIFACT_DIR,
        f"{repo_name}.zip"
    )

    file_count = 0

    with zipfile.ZipFile(
        artifact_path,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for current_dir, dirs, files in os.walk(root):
            dirs[:] = [
                name for name in dirs
                if name not in EXCLUDED_DIRS
                and not os.path.islink(
                    os.path.join(current_dir, name)
                )
            ]

            for filename in files:
                source_path = os.path.join(current_dir, filename)

                if os.path.islink(source_path):
                    continue

                relative_path = os.path.relpath(
                    source_path,
                    root
                )

                archive.write(source_path, relative_path)
                file_count += 1

    if file_count == 0:
        os.remove(artifact_path)
        raise ValueError("No project files found to build.")

    return {
        "status": "success",
        "artifact": os.path.basename(artifact_path),
        "file_count": file_count,
        "message": "Source bundle created successfully.",
        "application_code_executed": False
    }


if __name__ == "__main__":
    try:
        print(json.dumps(build_project(), indent=2))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(json.dumps({
            "status": "failed",
            "error": str(error)
        }, indent=2))
        sys.exit(1)
