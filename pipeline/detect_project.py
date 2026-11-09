
import json
import os
import re
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".github", ".venv", "venv", "__pycache__",
    "node_modules", "dist", "build", "target",
    ".next", ".idea", ".vscode", ".pytest_cache"
}

SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".php", ".java", ".go", ".rb", ".cs"
}

MAX_SOURCE_FILE_SIZE = 500_000
MAX_SOURCE_SCAN_SIZE = 5_000_000


def scan_files(root):
    root = Path(root)
    discovered = []

    for current, dirs, filenames in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for name in filenames:
            path = Path(current) / name
            discovered.append(path.relative_to(root).as_posix())

    return set(discovered)


def read_file(root, filename):
    path = Path(root) / filename

    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return ""


def find_file(files, filename):
    return next(
        (
            name for name in sorted(files)
            if Path(name).name.lower() == filename.lower()
        ),
        None
    )


def read_source_files(root, files):
    source_parts = []
    total_size = 0

    for filename in sorted(files):
        path = Path(root) / filename

        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue

        try:
            size = path.stat().st_size

            if size > MAX_SOURCE_FILE_SIZE:
                continue

            if total_size + size > MAX_SOURCE_SCAN_SIZE:
                break

            source_parts.append(read_file(root, filename))
            total_size += size

        except OSError:
            continue

    return "\n".join(source_parts)


def detect_application_type(result, source):
    """
    Detect application purpose using source-code evidence.

    Web and API flags are independent. A project can support both.
    Desktop detection checks actual import statements rather than
    arbitrary mentions of framework names.
    """

    source_lower = source.lower()

    desktop_patterns = [
        r"^\s*import\s+tkinter\b",
        r"^\s*from\s+tkinter\b",
        r"^\s*import\s+PyQt\d*\b",
        r"^\s*from\s+PyQt\d*\b",
        r"^\s*import\s+PySide\d*\b",
        r"^\s*from\s+PySide\d*\b",
        r"^\s*import\s+kivy\b",
        r"^\s*from\s+kivy\b",
        r"^\s*import\s+wx\b",
        r"^\s*from\s+wx\b",
        r"^\s*import\s+javafx\b",
        r"^\s*using\s+System\.Windows\.Forms",
        r"^\s*using\s+System\.Windows\.",
        r"require\s*\(\s*['\"]electron['\"]\s*\)",
        r"from\s+['\"]electron['\"]",
        r"import\s+.*\s+from\s+['\"]electron['\"]",
    ]

    worker_patterns = [
    r"^\s*from\s+celery\b",
    r"^\s*import\s+celery\b",
    r"^\s*from\s+dramatiq\b",
    r"^\s*import\s+dramatiq\b",
    r"^\s*from\s+rq\b",
    r"^\s*import\s+rq\b",
    r"^\s*from\s+apscheduler\b",
    r"^\s*import\s+apscheduler\b",
    r"require\s*\(\s*['\"]bullmq['\"]\s*\)",
    r"from\s+['\"]bullmq['\"]",
]

    is_desktop = any(
        re.search(
            pattern,
            source,
            re.MULTILINE | re.IGNORECASE
        )
        for pattern in desktop_patterns
    )

    is_worker = any(
        re.search(
            pattern,
            source,
            re.MULTILINE | re.IGNORECASE
        )
        for pattern in worker_patterns
    )

    framework = result["framework"]

    # API evidence
    api_patterns = [
        r"@app\.(get|post|put|patch|delete)\s*\(",
        r"@router\.(get|post|put|patch|delete)\s*\(",
        r"@api_view\s*\(",
        r"@restcontroller\b",
        r"@getmapping\b",
        r"@postmapping\b",
        r"fastapi\s*\(",
        r"express\s*\(",
        r"app\.listen\s*\(",
        r"router\.(get|post|put|patch|delete)\s*\(",
    ]

    is_api = any(
        re.search(pattern, source_lower)
        for pattern in api_patterns
    )

    # Web evidence
    web_patterns = [
        r"render_template\s*\(",
        r"render_template_string\s*\(",
        r"app\.route\s*\(",
        r"@app\.(get|post)\s*\(\s*['\"]/(?!api/)",
        r"next/",
        r"react-dom",
        r"createroot\s*\(",
        r"angular",
        r"vue",
        r"svelte",
        r"app\.use\s*\(\s*express\.static",
    ]

    is_web = any(
        re.search(pattern, source_lower)
        for pattern in web_patterns
    )

    # Framework and project metadata can provide additional evidence.
    if framework in {"React", "Next.js", "Vite", "Angular"}:
        is_web = True

    if framework in {"FastAPI", "Express"}:
        is_api = True

    if result["project_type"] == "static":
        result["application_type"] = "static"
        is_web = True

    elif is_desktop:
        result["application_type"] = "desktop_application"

    elif is_web and is_api:
        result["application_type"] = "web_application"

    elif is_web:
        result["application_type"] = "web_application"

    elif is_api:
        result["application_type"] = "api_service"

    elif is_worker:
        result["application_type"] = "background_worker"

    else:
        result["application_type"] = "custom"
        result["recommendations"].append(
            "Application purpose needs manual review."
        )

    result["is_web"] = is_web
    result["is_api"] = is_api
    result["is_worker"] = is_worker
    result["is_desktop"] = is_desktop


def detect_project(root):
    root = Path(root).resolve()

    if not root.is_dir():
        raise ValueError("Repository directory not found.")

    files = scan_files(root)
    root_files = {
        Path(name).name.lower() for name in files
    }

    result = {
        "project_type": "unknown",
        "language": "unknown",
        "framework": "unknown",
        "build_tool": "unknown",
        "entry_point": None,
        "detected_files": [],
        "deployment_files": [],
        "confidence": "low",
        "recommendations": [],
        "application_type": None,
        "is_web": False,
        "is_api": False,
        "is_worker": False,
        "is_desktop": False,
    }

    # JavaScript / Node.js
    package_path = find_file(files, "package.json")

    if package_path:
        result["project_type"] = "nodejs"
        result["language"] = "JavaScript"

        try:
            package = json.loads(read_file(root, package_path))

            if not isinstance(package, dict):
                raise ValueError("Invalid package.json structure.")

        except (json.JSONDecodeError, ValueError):
            package = {}
            result["recommendations"].append(
                "package.json is invalid or has an unexpected structure."
            )

        dependencies = {}

        for section in ("dependencies", "devDependencies"):
            values = package.get(section, {})

            if isinstance(values, dict):
                dependencies.update(values)

        if "next" in dependencies:
            result["framework"] = "Next.js"
        elif "vite" in dependencies:
            result["framework"] = "Vite"
        elif "react" in dependencies:
            result["framework"] = "React"
        elif "@angular/core" in dependencies:
            result["framework"] = "Angular"
        elif "express" in dependencies:
            result["framework"] = "Express"
        else:
            result["framework"] = "Node.js"

        result["entry_point"] = package.get("main")

        result["build_tool"] = (
            "npm" if "package-lock.json" in root_files
            else "yarn" if "yarn.lock" in root_files
            else "pnpm" if "pnpm-lock.yaml" in root_files
            else "npm (lockfile not detected)"
        )

        result["detected_files"].append(package_path)
        result["confidence"] = "high"

    # Python
    elif any(
        Path(name).suffix.lower() == ".py"
        or Path(name).name.lower() in {
            "requirements.txt", "pyproject.toml", "pipfile"
        }
        for name in files
    ):
        result["project_type"] = "python"
        result["language"] = "Python"

        requirements_path = find_file(files, "requirements.txt")
        pyproject_path = find_file(files, "pyproject.toml")

        requirements = (
            read_file(root, requirements_path).lower()
            if requirements_path else ""
        )

        pyproject = (
            read_file(root, pyproject_path).lower()
            if pyproject_path else ""
        )

        combined = requirements + "\n" + pyproject

        if "django" in combined:
            result["framework"] = "Django"
        elif "fastapi" in combined:
            result["framework"] = "FastAPI"
        elif "flask" in combined:
            result["framework"] = "Flask"
        else:
            result["framework"] = "Python"

        python_files = sorted(
            name for name in files
            if Path(name).suffix.lower() == ".py"
        )

        result["entry_point"] = next(
            (
                name for name in python_files
                if Path(name).name.lower() in {
                    "app.py", "main.py", "manage.py"
                }
            ),
            python_files[0] if python_files else None
        )

        result["build_tool"] = (
            "pip" if requirements_path
            else "pyproject.toml" if pyproject_path
            else "unknown"
        )

        result["detected_files"] = python_files[:30]

        result["confidence"] = "medium"

    # Java
    elif (
        find_file(files, "pom.xml")
        or find_file(files, "build.gradle")
        or find_file(files, "build.gradle.kts")
    ):
        result["project_type"] = "java"
        result["language"] = "Java"

        pom_path = find_file(files, "pom.xml")
        gradle_path = (
            find_file(files, "build.gradle")
            or find_file(files, "build.gradle.kts")
        )

        result["build_tool"] = (
            "Maven" if pom_path else "Gradle"
        )

        build_content = (
            read_file(root, pom_path)
            if pom_path else read_file(root, gradle_path)
        ).lower()

        result["framework"] = (
            "Spring Boot" if "spring-boot" in build_content
            else "Java"
        )

        result["confidence"] = "high"

    # PHP
    elif find_file(files, "composer.json"):
        composer_path = find_file(files, "composer.json")

        result["project_type"] = "php"
        result["language"] = "PHP"

        composer = read_file(root, composer_path).lower()

        result["framework"] = (
            "Laravel" if "laravel/framework" in composer else "PHP"
        )

        result["build_tool"] = "Composer"
        result["entry_point"] = "public/index.php"
        result["confidence"] = "high"

    # Static website
    elif find_file(files, "index.html"):
        result["project_type"] = "static"
        result["language"] = "HTML/CSS/JavaScript"
        result["framework"] = "Static Website"
        result["entry_point"] = find_file(files, "index.html")
        result["build_tool"] = "None"
        result["confidence"] = "medium"

    # Existing Docker configuration
    for filename in sorted(files):
        base_name = Path(filename).name.lower()

        if base_name == "dockerfile":
            result["deployment_files"].append(filename)

        elif base_name in {
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        }:
            result["deployment_files"].append(filename)

        elif base_name == "nginx.conf":
            result["deployment_files"].append(filename)

    # Important project files
    important_files = {
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "pom.xml",
        "composer.json",
        "index.html",
    }

    result["detected_files"] = list(dict.fromkeys(
        result["detected_files"] + sorted(
            name for name in files
            if Path(name).name.lower() in important_files
        )
    ))

    # Application classification
    source = read_source_files(root, files)
    detect_application_type(result, source)

    if result["project_type"] == "unknown":
        result["recommendations"].append(
            "Project type could not be identified automatically. "
            "Manual configuration may be required."
        )

    if not result["deployment_files"]:
        result["recommendations"].append(
            "Docker and Nginx deployment configuration may need to be generated."
        )

    return result


if __name__ == "__main__":
    project_path = os.environ.get(
        "PROJECT_PATH",
        "/workspace/Smart-Route-and-Data-Analyzer"
    )

    try:
        print(json.dumps(
            detect_project(project_path),
            indent=2
        ))
    except ValueError as error:
        raise SystemExit(f"Error: {error}")
