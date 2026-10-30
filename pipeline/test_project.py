
import ast
import json
import os
import sys


EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}


def validate_project(root):
    errors = []
    checked_files = []

    for current_dir, dirs, files in os.walk(root):
        dirs[:] = [
            name for name in dirs
            if name not in EXCLUDED_DIRS
            and not os.path.islink(os.path.join(current_dir, name))
        ]

        for filename in files:
            path = os.path.join(current_dir, filename)

            if os.path.islink(path):
                continue

            relative_path = os.path.relpath(path, root)

            if filename.endswith(".py"):
                try:
                    with open(path, "r", encoding="utf-8") as source:
                        content = source.read()

                    ast.parse(content, filename=relative_path)
                    checked_files.append(relative_path)

                except (SyntaxError, UnicodeDecodeError, OSError) as error:
                    errors.append({
                        "file": relative_path,
                        "error": str(error)
                    })

            elif filename == "package.json":
                try:
                    with open(path, "r", encoding="utf-8") as source:
                        json.load(source)

                    checked_files.append(relative_path)

                except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
                    errors.append({
                        "file": relative_path,
                        "error": str(error)
                    })

    if not checked_files:
        errors.append({
            "file": ".",
            "error": "No supported Python files or package.json found."
        })

    result = {
        "status": "passed" if not errors else "failed",
        "checks": checked_files,
        "checked_count": len(checked_files),
        "errors": errors,
        "code_executed": False
    }

    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    project_root = os.environ.get(
        "PROJECT_PATH",
        "/workspace/Smart-Route-and-Data-Analyzer"
    )

    if not os.path.isdir(project_root):
        print(json.dumps({
            "status": "failed",
            "errors": [{"error": "Repository directory not found."}]
        }, indent=2))
        sys.exit(1)

    sys.exit(validate_project(project_root))
