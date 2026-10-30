
import json
import os

def detect_project(root):
    files = set(os.listdir(root))
    result = {
        "project_type": "unknown",
        "language": "unknown",
        "detected_files": []
    }

    if "package.json" in files:
        result["project_type"] = "nodejs"
        result["language"] = "JavaScript"
        result["detected_files"].append("package.json")

    elif any(name.endswith(".py") for name in files):
        result["project_type"] = "python"
        result["language"] = "Python"
        result["detected_files"] = [
            name for name in files if name.endswith(".py")
        ]

    elif "Dockerfile" in files:
        result["project_type"] = "docker"
        result["language"] = "Docker"
        result["detected_files"].append("Dockerfile")

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    project_path = os.environ.get(
        "PROJECT_PATH",
        "/workspace/Smart-Route-and-Data-Analyzer"
    )

    if not os.path.isdir(project_path):
        raise SystemExit("Error: Repository directory not found.")

    detect_project(project_path)
