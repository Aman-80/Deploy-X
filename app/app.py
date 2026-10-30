
from flask import Flask, jsonify, render_template, request, send_file
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import sqlite3
import os
import re
import json


app = Flask(__name__)

DB_PATH = "/data/deployx.db"
REPOSITORIES_PATH = "/repositories"
WORKER_API_URL = "http://deployx-worker-api:8000"
GUI_CONTROLLER_URL = "http://deployx-gui:6082"
DOCKER_API_URL = os.environ.get(
    "DOCKER_API_URL",
    "http://docker-monitoring-gateway:8080"
)


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                branch TEXT NOT NULL DEFAULT 'main',
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository_id INTEGER NOT NULL,
                repository_name TEXT NOT NULL,
                branch TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'queued',
                status TEXT NOT NULL DEFAULT 'queued',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_seconds REAL,
                logs TEXT NOT NULL DEFAULT ''
            )
        """)


init_db()


def valid_github_url(url):
    if not isinstance(url, str):
        return False

    parsed = urlparse(url)

    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        return False

    parts = parsed.path.strip("/").split("/")

    if len(parts) != 2:
        return False

    username, repository = parts

    return all(
        re.fullmatch(r"[A-Za-z0-9-]+", part) is not None
        for part in (username, repository.removesuffix(".git"))
    )


def get_repository_folder(url):
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1].removesuffix(".git")


def get_repository(repository_id):
    with get_db() as db:
        return db.execute(
            """
            SELECT id, name, url, branch, created_at
            FROM repositories
            WHERE id = ?
            """,
            (repository_id,)
        ).fetchone()


def worker_post(endpoint, payload, timeout=65):
    body = json.dumps(payload).encode("utf-8")

    worker_request = Request(
        f"{WORKER_API_URL}/{endpoint}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(worker_request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
            return jsonify(result), response.status

    except HTTPError as error:
        try:
            result = json.loads(error.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            result = {"error": "The DeployX worker request failed."}

        return jsonify(result), error.code

    except (URLError, TimeoutError, OSError) as error:
        return jsonify({
            "error": "Could not reach the DeployX worker.",
            "details": str(error)
        }), 502

    except (ValueError, UnicodeDecodeError):
        return jsonify({
            "error": "The worker returned an invalid response."
        }), 502


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.get("/api/status")
def status():
    with get_db() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM repositories"
        ).fetchone()[0]

    return jsonify({
        "project": "DeployX",
        "status": "running",
        "repositories": count,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.get("/api/containers")
def list_docker_containers():
    try:
        docker_request = Request(
            f"{DOCKER_API_URL}/containers/json?all=1",
            headers={"Accept": "application/json"},
            method="GET"
        )

        with urlopen(docker_request, timeout=5) as response:
            containers = json.loads(
                response.read().decode("utf-8")
            )

        if not isinstance(containers, list):
            return jsonify({
                "error": "Unexpected response from Docker API"
            }), 502

        container_list = []

        for container in containers:
            ports = container.get("Ports") or []
            names = container.get("Names") or []

            container_list.append({
                "id": container.get("Id", "")[:12],
                "name": ", ".join(
                    name.lstrip("/")
                    for name in names
                    if isinstance(name, str)
                ),
                "image": container.get("Image", "Unknown"),
                "state": container.get("State", "unknown"),
                "status": container.get("Status", ""),
                "ports": [
                    {
                        "ip": port.get("IP", ""),
                        "private": port.get("PrivatePort"),
                        "public": port.get("PublicPort"),
                        "type": port.get("Type", "")
                    }
                    for port in ports
                    if isinstance(port, dict)
                ]
            })

        return jsonify({
            "containers": container_list,
            "count": len(container_list),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        return jsonify({
            "error": "Docker monitoring is unavailable",
            "details": str(error)
        }), 502

@app.get("/api/pipeline-runs")
def list_pipeline_runs():
    with get_db() as db:
        rows = db.execute("""
            SELECT
                id,
                repository_id,
                repository_name,
                branch,
                stage,
                status,
                started_at,
                finished_at,
                duration_seconds,
                logs
            FROM pipeline_runs
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

    return jsonify([dict(row) for row in rows]), 200


@app.get("/api/pipeline-runs/<int:run_id>/artifact")
def download_pipeline_artifact(run_id):
    with get_db() as db:
        run = db.execute(
            """
            SELECT status, logs
            FROM pipeline_runs
            WHERE id = ?
            """,
            (run_id,)
        ).fetchone()

    if run is None:
        return jsonify({"error": "Pipeline run not found."}), 404

    if run["status"] != "success":
        return jsonify({
            "error": "Only successful pipeline runs can be downloaded."
        }), 409

    try:
        result = json.loads(run["logs"])
    except (ValueError, TypeError):
        return jsonify({
            "error": "Build artifact information is invalid."
        }), 500

    artifact = result.get("artifact")

    if (
        not isinstance(artifact, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}\.zip", artifact)
    ):
        return jsonify({
            "error": "This pipeline run has no downloadable ZIP artifact."
        }), 404

    artifact_root = os.path.realpath("/artifacts")
    candidate = os.path.join(artifact_root, artifact)
    artifact_path = os.path.realpath(candidate)

    if (
        os.path.islink(candidate)
        or os.path.commonpath([artifact_root, artifact_path]) != artifact_root
        or not os.path.isfile(artifact_path)
    ):
        return jsonify({
            "error": "Artifact file was not found in storage."
        }), 404

    return send_file(
        artifact_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=artifact
    )




@app.get("/api/repositories")
def list_repositories():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM repositories ORDER BY id DESC"
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@app.get("/api/repositories/<int:repository_id>/detect")
def detect_repository_project(repository_id):
    repo = get_repository(repository_id)

    if repo is None:
        return jsonify({"error": "Repository not found."}), 404

    repo_name = get_repository_folder(repo["url"])
    root = os.path.join(REPOSITORIES_PATH, repo_name)

    if not os.path.isdir(root):
        return jsonify({
            "error": "Repository has not been checked out yet."
        }), 404

    detected_files = []

    for current_dir, dirs, files in os.walk(root):
        dirs[:] = [
            directory for directory in dirs
            if directory != ".git"
        ]

        for filename in files:
            relative_path = os.path.relpath(
                os.path.join(current_dir, filename),
                root
            )
            detected_files.append(relative_path)

    top_level_files = set(detected_files)

    python_files = sorted(
        filename for filename in detected_files
        if filename.endswith(".py")
    )

    if "package.json" in top_level_files:
        project_type = "nodejs"
        language = "JavaScript"
        detected = ["package.json"]

    elif python_files:
        project_type = "python"
        language = "Python"
        detected = python_files[:20]

    elif "Dockerfile" in top_level_files:
        project_type = "docker"
        language = "Docker"
        detected = ["Dockerfile"]

    else:
        project_type = "unknown"
        language = "unknown"
        detected = sorted(top_level_files)[:20]

    return jsonify({
        "repository_id": repo["id"],
        "repository": repo["name"],
        "branch": repo["branch"],
        "project_type": project_type,
        "language": language,
        "detected_files": detected
    }), 200


@app.post("/api/repositories/<int:repository_id>/checkout")
def checkout_repository(repository_id):
    repo = get_repository(repository_id)

    if repo is None:
        return jsonify({"error": "Repository not found."}), 404

    repo_name = get_repository_folder(repo["url"])
    repository_path = os.path.join(REPOSITORIES_PATH, repo_name)

    if os.path.isdir(repository_path):
        git_directory = os.path.join(repository_path, ".git")

        if os.path.isdir(git_directory):
            return jsonify({
                "status": "already_checked_out",
                "repository": repo["name"],
                "branch": repo["branch"],
                "message": (
                    "Repository already exists in persistent storage. "
                    "Duplicate checkout skipped."
                )
            }), 200

        return jsonify({
            "error": (
                "A directory with this repository name already exists, "
                "but it is not a valid Git checkout. Manual review is needed."
            )
        }), 409

    return worker_post(
        "checkout",
        {
            "url": repo["url"],
            "branch": repo["branch"]
        },
        timeout=130
    )


@app.post("/api/repositories/<int:repository_id>/test")
def test_repository(repository_id):
    repo = get_repository(repository_id)

    if repo is None:
        return jsonify({"error": "Repository not found."}), 404

    repo_name = get_repository_folder(repo["url"])
    repository_path = os.path.join(REPOSITORIES_PATH, repo_name)

    if not os.path.isdir(repository_path):
        return jsonify({
            "error": "Repository has not been checked out yet."
        }), 404

    started = datetime.now(timezone.utc)

    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO pipeline_runs (
                repository_id, repository_name, branch,
                stage, status, started_at, logs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo["id"],
                repo["name"],
                repo["branch"],
                "validation",
                "running",
                started.isoformat(),
                "Project validation started."
            )
        )
        run_id = cursor.lastrowid

    response, http_status = worker_post(
        "test",
        {"repository": repo_name},
        timeout=65
    )

    result = response.get_json(silent=True) or {
        "error": "No valid response from worker."
    }

    passed = http_status == 200 and result.get("status") == "passed"
    final_status = "success" if passed else "failed"

    finished = datetime.now(timezone.utc)
    duration = round((finished - started).total_seconds(), 2)
    logs = json.dumps(result)[:10000]

    with get_db() as db:
        db.execute(
            """
            UPDATE pipeline_runs
            SET status = ?, stage = ?, finished_at = ?,
                duration_seconds = ?, logs = ?
            WHERE id = ?
            """,
            (
                final_status,
                "completed" if passed else "validation_failed",
                finished.isoformat(),
                duration,
                logs,
                run_id
            )
        )

    result["run_id"] = run_id
    result["pipeline_status"] = final_status
    result["duration_seconds"] = duration

    return jsonify(result), http_status


@app.post("/api/repositories/<int:repository_id>/build")
def build_repository(repository_id):
    repo = get_repository(repository_id)

    if repo is None:
        return jsonify({"error": "Repository not found."}), 404

    repo_name = get_repository_folder(repo["url"])
    repository_path = os.path.join(REPOSITORIES_PATH, repo_name)

    if not os.path.isdir(repository_path):
        return jsonify({
            "error": "Repository has not been checked out yet."
        }), 404

    started = datetime.now(timezone.utc)

    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO pipeline_runs (
                repository_id, repository_name, branch,
                stage, status, started_at, logs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo["id"],
                repo["name"],
                repo["branch"],
                "build",
                "running",
                started.isoformat(),
                "Source bundle build started."
            )
        )
        run_id = cursor.lastrowid

    response, http_status = worker_post(
        "build",
        {"repository": repo_name},
        timeout=125
    )

    result = response.get_json(silent=True) or {
        "error": "No valid response from worker."
    }

    successful = (
        http_status == 200
        and result.get("status") == "success"
    )

    finished = datetime.now(timezone.utc)
    duration = round((finished - started).total_seconds(), 2)

    final_status = "success" if successful else "failed"
    final_stage = "completed" if successful else "build_failed"
    logs = json.dumps(result)[:10000]

    with get_db() as db:
        db.execute(
            """
            UPDATE pipeline_runs
            SET status = ?, stage = ?, finished_at = ?,
                duration_seconds = ?, logs = ?
            WHERE id = ?
            """,
            (
                final_status,
                final_stage,
                finished.isoformat(),
                duration,
                logs,
                run_id
            )
        )

    result["run_id"] = run_id
    result["pipeline_status"] = final_status
    result["duration_seconds"] = duration

    return jsonify(result), http_status


@app.post("/api/repositories")
def add_repository():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A valid JSON object is required."}), 400

    url = data.get("url", "")
    branch = data.get("branch", "main")
    name = data.get("name", "")

    if not all(
        isinstance(value, str)
        for value in (url, branch, name)
    ):
        return jsonify({
            "error": "Repository URL, branch, and name must be strings."
        }), 400

    url = url.strip().rstrip("/")
    branch = branch.strip()
    name = name.strip()

    if not valid_github_url(url):
        return jsonify({
            "error": "Enter a valid HTTPS GitHub repository URL."
        }), 400

    if not branch or len(branch) > 100:
        return jsonify({
            "error": "Enter a valid branch name."
        }), 400

    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        return jsonify({
            "error": "Branch name contains invalid characters."
        }), 400

    if not name:
        name = get_repository_folder(url)

    if len(name) > 100:
        return jsonify({
            "error": "Repository name is too long."
        }), 400

    try:
        with get_db() as db:
            cursor = db.execute(
                """
                INSERT INTO repositories (name, url, branch, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    url,
                    branch,
                    datetime.now(timezone.utc).isoformat()
                )
            )
            repository_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        return jsonify({
            "error": "This repository has already been added."
        }), 409

    return jsonify({
        "message": "Repository saved successfully.",
        "repository": {
            "id": repository_id,
            "name": name,
            "url": url,
            "branch": branch
        }
    }), 201


@app.post("/api/repositories/<int:repository_id>/deploy")
def deploy_repository(repository_id):
    repo = get_repository(repository_id)

    if repo is None:
        return jsonify({"error": "Repository not found."}), 404

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400

    source_run_id = data.get("run_id")

    if (
        isinstance(source_run_id, bool)
        or not isinstance(source_run_id, int)
        or source_run_id < 1
    ):
        return jsonify({
            "error": "Provide a valid successful build run_id."
        }), 400

    with get_db() as db:
        source_run = db.execute(
            """
            SELECT id, logs
            FROM pipeline_runs
            WHERE id = ?
              AND repository_id = ?
              AND status = 'success'
            """,
            (source_run_id, repository_id)
        ).fetchone()

    if source_run is None:
        return jsonify({
            "error": "Successful build run not found for this repository."
        }), 404

    try:
        build_result = json.loads(source_run["logs"])
    except (ValueError, TypeError):
        return jsonify({
            "error": "Build run logs are invalid."
        }), 400

    artifact = build_result.get("artifact")

    if (
        not isinstance(artifact, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}\.zip",
            artifact
        )
    ):
        return jsonify({
            "error": "Selected run does not contain a valid ZIP artifact."
        }), 400

    started = datetime.now(timezone.utc)

    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO pipeline_runs (
                repository_id, repository_name, branch,
                stage, status, started_at, logs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo["id"],
                repo["name"],
                repo["branch"],
                "deployment",
                "running",
                started.isoformat(),
                f"Deploying {artifact} from build run #{source_run_id}."
            )
        )
        deployment_run_id = cursor.lastrowid

    payload = json.dumps({"artifact": artifact}).encode("utf-8")
    controller_request = Request(
        f"{GUI_CONTROLLER_URL}/deploy",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(controller_request, timeout=30) as response:
            controller_status = response.status
            result = json.loads(response.read().decode("utf-8"))

    except HTTPError as error:
        controller_status = error.code
        try:
            result = json.loads(error.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            result = {"error": "Deployment controller rejected the request."}

    except (URLError, TimeoutError, OSError) as error:
        controller_status = 502
        result = {
            "error": "Could not reach the GUI deployment controller.",
            "details": str(error)
        }

    successful = (
        controller_status == 200
        and result.get("status") == "deployed"
    )

    finished = datetime.now(timezone.utc)
    duration = round((finished - started).total_seconds(), 2)
    final_status = "success" if successful else "failed"
    final_stage = "deployed" if successful else "deploy_failed"
    logs = json.dumps(result)[:10000]

    with get_db() as db:
        db.execute(
            """
            UPDATE pipeline_runs
            SET status = ?, stage = ?, finished_at = ?,
                duration_seconds = ?, logs = ?
            WHERE id = ?
            """,
            (
                final_status,
                final_stage,
                finished.isoformat(),
                duration,
                logs,
                deployment_run_id
            )
        )

    result["deployment_run_id"] = deployment_run_id
    result["source_build_run_id"] = source_run_id
    result["pipeline_status"] = final_status
    result["duration_seconds"] = duration

    return jsonify(result), (
        200 if successful else
        controller_status if controller_status >= 400 else 502
    )



@app.get("/api/health")
def api_health():
    return health()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
