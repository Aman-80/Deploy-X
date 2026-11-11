"""DeployX deployment bundle generator.

Generates reviewable deployment artifacts without building or running the
application. The original project directory is never modified.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .detect_project import detect_project
except ImportError:  # Supports direct execution from the pipeline directory.
    from detect_project import detect_project


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    ".next",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".terraform",
    "coverage",
    ".aws",
    ".ssh",
    ".kube",
    ".azure",
    ".gnupg",
}

ENV_EXCEPTIONS = {
    ".env.example",
    ".env.sample",
    ".env.template",
}

SENSITIVE_FILE_NAMES = {
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "credentials.json",
    ".git-credentials",
    "id_rsa",
    "id_ed25519",
}

SENSITIVE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".ppk",
    ".jks",
    ".keystore",
    ".tfstate",
)

DEFAULT_HOST_PORT = 8081


def should_skip_file(filename: str) -> bool:
    """Return True for files that should not enter the generated source copy."""
    lower_name = filename.lower()

    if lower_name == ".dockerignore":
        return True

    if lower_name in SENSITIVE_FILE_NAMES:
        return True

    if lower_name == ".env" or (
        lower_name.startswith(".env.") and lower_name not in ENV_EXCEPTIONS
    ):
        return True

    if lower_name.endswith(SENSITIVE_SUFFIXES):
        return True

    return False


def build_dockerignore() -> str:
    """Return strict build-context exclusions.

    Safe environment templates remain in the generated source snapshot for
    human review, but are excluded from image build contexts so they cannot be
    copied into a runtime image or accidentally served by a static site.
    """
    return """\
.git
.venv
venv
__pycache__
node_modules
.pytest_cache
.mypy_cache
.ruff_cache
.tox
.terraform
coverage
dist
build
.next
.env
.env.*
.npmrc
.pypirc
.netrc
.git-credentials
credentials
credentials.json
id_rsa
id_ed25519
*.pem
*.key
*.p12
*.pfx
*.ppk
*.jks
*.keystore
*.tfstate
*.tfstate.*
Dockerfile.original
*.py[cod]
.DS_Store
Thumbs.db
"""


def copy_project_source(root: Path | str, source_dir: Path | str) -> dict[str, Any]:
    """Copy a safe source snapshot, excluding caches, symlinks and secrets."""
    root = Path(root).resolve()
    source_dir = Path(source_dir).resolve()

    if source_dir == root or root in source_dir.parents:
        raise ValueError("Generated source snapshot cannot be inside the original project.")

    source_dir.mkdir(parents=True, exist_ok=True)
    copied_files = 0
    skipped_files = 0

    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if name not in IGNORED_DIRS and not (current_path / name).is_symlink()
        ]

        relative_path = current_path.relative_to(root)
        destination = source_dir / relative_path
        destination.mkdir(parents=True, exist_ok=True)

        for filename in files:
            source_file = current_path / filename
            if source_file.is_symlink() or should_skip_file(filename):
                skipped_files += 1
                continue

            target_file = destination / filename
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
            copied_files += 1

    (source_dir / ".dockerignore").write_text(
        build_dockerignore(), encoding="utf-8"
    )

    return {"copied_files": copied_files, "skipped_files": skipped_files}



# Only mount application data directories, never arbitrary operating-system paths.
_ALLOWED_PERSISTENT_ROOTS = {"data", "repositories", "uploads", "storage", "media", "artifacts"}
_STORAGE_NAME_TOKENS = {
    "DB", "DATABASE", "SQLITE", "REPOSITORY", "REPOSITORIES", "UPLOAD",
    "STORAGE", "MEDIA", "ARTIFACT", "ARTIFACTS", "WORKSPACE", "DATA",
}
_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _storage_directory_from_assignment(name: str, value: str) -> str | None:
    """Resolve a declared application storage path to a safe container directory.

    This deliberately uses conservative AST-based discovery. It only considers
    path-like variable names with storage-related semantics and a literal
    absolute POSIX path. It does not execute or import application code.
    """
    upper_name = name.upper()
    if not any(token in upper_name for token in _STORAGE_NAME_TOKENS):
        return None
    if not any(marker in upper_name for marker in ("PATH", "DIR", "ROOT", "FILE")):
        return None

    candidate = PurePosixPath(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None

    normalized = str(candidate)
    parts = candidate.parts
    if len(parts) < 2:
        return None

    # Allow conventional application-data roots, not system paths such as
    # /etc, /usr, /root, /home, /tmp or /var/run.
    root_name = parts[1]
    if root_name not in _ALLOWED_PERSISTENT_ROOTS:
        return None

    # A DB/file path maps its parent directory; directory paths map themselves.
    is_file_path = (
        "DB" in upper_name
        or "DATABASE" in upper_name
        or "SQLITE" in upper_name
        or candidate.suffix.lower() in _DATABASE_SUFFIXES
        or upper_name.endswith("_FILE")
    )
    directory = candidate.parent if is_file_path else candidate
    if str(directory) in {"/", "."}:
        return None
    return str(directory)


def detect_persistent_directories(project_root: Path | str) -> list[str]:
    """Discover conservative Python application storage paths without imports.

    Examples: DB_PATH='/data/app.db' becomes /data; REPOSITORIES_PATH='/repositories'
    remains /repositories. Only explicit literal assignments are considered.
    """
    root = Path(project_root).resolve()
    discovered: set[str] = set()
    python_files_seen = 0

    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name not in IGNORED_DIRS and not (current_path / name).is_symlink()
        ]
        for filename in files:
            if not filename.endswith('.py'):
                continue
            source_file = current_path / filename
            if source_file.is_symlink():
                continue
            python_files_seen += 1
            if python_files_seen > 500:
                break
            try:
                source_text = source_file.read_text(encoding='utf-8')
                if len(source_text) > 2_000_000:
                    continue
                tree = ast.parse(source_text, filename=str(source_file))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    targets = node.targets
                    value_node = node.value
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                    value_node = node.value
                else:
                    continue

                if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
                    continue
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    directory = _storage_directory_from_assignment(target.id, value_node.value)
                    if directory:
                        discovered.add(directory)
        if python_files_seen > 500:
            break

    # Collapse nested mount points so /data and /data/uploads do not create
    # overlapping named volumes.
    ordered = sorted(discovered, key=lambda item: (item.count('/'), item))
    result: list[str] = []
    for directory in ordered:
        if not any(directory == parent or directory.startswith(parent.rstrip('/') + '/') for parent in result):
            result.append(directory)
    return result


def _storage_volume_name(directory: str) -> str:
    """Convert a safe absolute mount target into a stable Compose volume key."""
    label = re.sub(r"[^a-z0-9]+", "-", directory.strip('/').lower()).strip('-')
    return f"app-{label or 'data'}"


def _storage_dockerfile_setup(storage_directories: list[str]) -> str:
    if not storage_directories:
        return ""
    safe_paths = " ".join(shlex.quote(path) for path in storage_directories)
    return f" && mkdir -p {safe_paths} && chown -R app:app {safe_paths}"

def get_python_module(entry: str) -> str:
    """Convert a safe Python entry-point path into an importable module path."""
    entry_path = Path(entry)

    if entry_path.is_absolute() or ".." in entry_path.parts:
        raise ValueError("Unsafe Python entry point detected.")

    module = ".".join(entry_path.with_suffix("").parts)
    if not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", module
    ):
        raise ValueError("Python entry point is not a valid module path.")

    return module


def _validate_host_port(host_port: int | str | None) -> int:
    value: Any = host_port
    if value is None:
        value = os.environ.get("DEPLOYX_HOST_PORT", str(DEFAULT_HOST_PORT))

    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("DEPLOYX_HOST_PORT must be an integer between 1 and 65535.") from exc

    if not 1 <= port <= 65535:
        raise ValueError("DEPLOYX_HOST_PORT must be between 1 and 65535.")

    return port


def generate_static_nginx_config(spa_fallback: bool = False) -> str:
    """Generate an Nginx site config for static content or an SPA frontend."""
    route_fallback = "/index.html" if spa_fallback else "=404"
    return f'''# Generated by DeployX. Review before production use.
server {{
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location / {{
        try_files $uri $uri/ {route_fallback};
    }}
}}
'''


def generate_nginx_config(upstream: str) -> str:
    """Generate a reverse-proxy config with forwarding and WebSocket headers."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+:[0-9]{1,5}", upstream):
        raise ValueError("Invalid Nginx upstream value.")

    return f'''# Generated by DeployX. Review before production use.
map $http_upgrade $connection_upgrade {{
    default upgrade;
    '' close;
}}

server {{
    listen 80;
    server_name _;
    client_max_body_size 20m;

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_connect_timeout 10s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}
'''


def _python_healthcheck(port: int) -> str:
    return (
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 "
        f"CMD python -c \"import socket; s=socket.create_connection(('127.0.0.1',{port}),3); s.close()\" || exit 1"
    )


def _node_healthcheck(port: int) -> str:
    command = (
        "const net=require('net');"
        f"const s=net.createConnection({port},'127.0.0.1');"
        "s.setTimeout(3000);"
        "s.on('connect',()=>{s.end();process.exit(0)});"
        "s.on('timeout',()=>{s.destroy();process.exit(1)});"
        "s.on('error',()=>process.exit(1));"
    )
    return (
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 "
        f'CMD node -e "{command}"'
    )


def _nginx_healthcheck() -> str:
    return (
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 "
        "CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1"
    )


def _python_dockerfile(
    module: str,
    framework: str,
    port: int,
    has_requirements: bool,
    storage_directories: list[str] | None = None,
) -> tuple[str, str]:
    if framework == "Flask":
        install_runtime = (
            "python -m pip install --no-cache-dir gunicorn flask"
        )
        command = f'CMD ["gunicorn", "--bind", "0.0.0.0:{port}", "{module}:app"]'
        comment = "Confirm the detected module exports a Flask application named 'app'."
    else:
        install_runtime = (
            'python -m pip install --no-cache-dir "uvicorn[standard]" fastapi'
        )
        command = (
            f'CMD ["uvicorn", "{module}:app", "--host", "0.0.0.0", '
            f'"--port", "{port}"]'
        )
        comment = "Confirm the detected module exports an ASGI application named 'app'."

    requirements_copy = "COPY requirements.txt ./\n" if has_requirements else ""
    dockerfile = f'''FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies before switching to the unprivileged runtime user.
RUN python -m pip install --no-cache-dir --upgrade pip
{requirements_copy}RUN if [ -f requirements.txt ]; then \\
        python -m pip install --no-cache-dir -r requirements.txt; \\
    fi && {install_runtime}

RUN groupadd --system app && useradd --system --gid app --create-home app && chown app:app /app{_storage_dockerfile_setup(storage_directories or [])}
COPY --chown=app:app . .
USER app

EXPOSE {port}
{_python_healthcheck(port)}
{command}
'''
    return dockerfile, comment


def _express_dockerfile(port: int = 3000) -> str:
    return f'''FROM node:22-alpine

ENV NODE_ENV=production
WORKDIR /app

# Keep the application directory writable by the unprivileged node user.
RUN chown node:node /app
COPY --chown=node:node package*.json ./
USER node
RUN if [ -f package-lock.json ]; then \\
        npm ci --omit=dev; \\
    else \\
        npm install --omit=dev; \\
    fi
COPY --chown=node:node . .

EXPOSE {port}
{_node_healthcheck(port)}
CMD ["npm", "start"]
'''


def _frontend_dockerfile(output_dir: str) -> str:
    return f'''FROM node:22-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/{output_dir} /usr/share/nginx/html
EXPOSE 80
{_nginx_healthcheck()}
'''


def _static_dockerfile() -> str:
    return f'''FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
{_nginx_healthcheck()}
'''


def _generate_compose(
    *,
    is_static: bool,
    app_port: int,
    host_port: int,
    has_nginx_proxy: bool,
    storage_directories: list[str] | None = None,
) -> str:
    published_port = f'"${{DEPLOYX_HOST_PORT:-{host_port}}}:80"'
    storage_directories = storage_directories or []
    storage_mount_lines = "".join(
        f"      - {_storage_volume_name(directory)}:{directory}\n"
        for directory in storage_directories
    )
    storage_volume_definitions = "".join(
        f"  {_storage_volume_name(directory)}:\n"
        for directory in storage_directories
    )
    storage_service_block = f"    volumes:\n{storage_mount_lines}" if storage_directories else ""
    top_level_volumes = f"\nvolumes:\n{storage_volume_definitions}" if storage_directories else ""

    if is_static:
        return f'''services:
  app:
    build:
      context: ./source
      dockerfile: Dockerfile
    init: true
    restart: unless-stopped
    ports:
      - {published_port}
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
'''

    if not has_nginx_proxy:
        raise ValueError("A reverse proxy is required for this application strategy.")

    return f'''services:
  app:
    build:
      context: ./source
      dockerfile: Dockerfile
    init: true
    restart: unless-stopped
    expose:
      - "{app_port}"
{storage_service_block}
  nginx:
    image: nginx:alpine
    init: true
    ports:
      - {published_port}
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      app:
        condition: service_healthy
    restart: unless-stopped
{top_level_volumes}'''


def _generate_jenkinsfile(host_port: int) -> str:
    # Use a plain string (not an f-string) so Groovy braces remain untouched.
    pipeline = r'''pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    stages {
        stage('Linux Agent Preflight & Validation') {
            steps {
                sh ''' + "'''" + r'''
                    set -eu
                    test "$(uname -s)" = "Linux"
                    command -v docker >/dev/null 2>&1
                    command -v curl >/dev/null 2>&1
                    docker info >/dev/null
                    docker compose version
                    docker compose config -q
                    test -f Dockerfile
                    test -f docker-compose.yml
                    test -f source/Dockerfile
                    test -f nginx.conf
                    test -d source
                    port="${DEPLOYX_HOST_PORT:-__HOST_PORT__}"
                    case "$port" in ''|*[!0-9]*) echo "Invalid DEPLOYX_HOST_PORT"; exit 1 ;; esac
                    test "$port" -ge 1 && test "$port" -le 65535
                ''' + "'''" + r'''
            }
        }

        stage('Build Approval') {
            steps {
                input message: 'Approve Docker image build? Build steps may execute repository scripts and install dependencies.',
                      ok: 'Approve Build'
            }
        }

        stage('Docker Build') {
            steps {
                sh 'docker compose build'
            }
        }

        stage('Deployment Approval') {
            steps {
                input message: 'Approve starting or updating the application on the configured host port?',
                      ok: 'Approve Deployment'
            }
        }

        stage('Deploy') {
            steps {
                sh ''' + "'''" + r'''
                    set -eu
                    export DEPLOYX_HOST_PORT="${DEPLOYX_HOST_PORT:-__HOST_PORT__}"
                    docker compose up -d
                    docker compose ps
                ''' + "'''" + r'''
            }
        }

        stage('Health Verification') {
            steps {
                sh ''' + "'''" + r'''
                    set -eu
                    port="${DEPLOYX_HOST_PORT:-__HOST_PORT__}"
                    health_path="${DEPLOYX_HEALTHCHECK_PATH:-/}"
                    case "$health_path" in
                        /*) ;;
                        *) echo "DEPLOYX_HEALTHCHECK_PATH must begin with /"; exit 1 ;;
                    esac
                    url="http://127.0.0.1:${port}${health_path}"
                    attempt=1
                    while [ "$attempt" -le 30 ]; do
                        status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url" 2>/dev/null || true)"
                        case "$status" in
                            2[0-9][0-9]|3[0-9][0-9])
                                echo "Application health endpoint responded with HTTP ${status}."
                                docker compose ps
                                exit 0
                                ;;
                        esac
                        if [ -n "$status" ]; then
                            echo "Health endpoint returned HTTP ${status}; expecting 2xx or 3xx."
                        else
                            echo "Health endpoint is not reachable yet."
                        fi
                        echo "Waiting for application health (${attempt}/30)..."
                        sleep 3
                        attempt=$((attempt + 1))
                    done
                    echo "Application did not become reachable at ${url}."
                    docker compose ps || true
                    docker compose logs --no-color --tail=100 || true
                    exit 1
                ''' + "'''" + r'''
            }
        }
    }

    post {
        success {
            echo 'DeployX build, deployment and endpoint verification completed.'
        }
        failure {
            echo 'Pipeline failed. Review the stage output and container logs.'
            sh 'docker compose ps || true'
            sh 'docker compose logs --no-color --tail=100 || true'
        }
        always {
            echo 'DeployX pipeline finished.'
        }
    }
}
'''
    return pipeline.replace("__HOST_PORT__", str(host_port))


def _write_deployment_readme(
    output: Path,
    *,
    project_type: str,
    framework: str,
    host_port: int,
    app_port: int,
    is_static: bool,
    warnings: list[str],
    storage_directories: list[str] | None = None,
) -> None:
    app_port_label = "80 (Nginx static server)" if is_static else str(app_port)
    storage_directories = storage_directories or []
    storage_text = (
        "\n".join(f"- `{directory}`: named Docker volume (persistent, writable by the application user)." for directory in storage_directories)
        if storage_directories else "- No persistent application directories were detected automatically. Review application file writes before production use."
    )
    warning_text = "\n".join(f"- {item}" for item in warnings) or "- No additional detector warnings."
    readme = f'''# DeployX Generated Deployment Bundle

## Detected project
- Type: {project_type}
- Framework: {framework}

## Generated files
- `Dockerfile`: generated container build instructions.
- `docker-compose.yml`: application service and published port mapping.
- `Jenkinsfile`: Linux-first Jenkins pipeline with preflight checks, two approval gates, build, deployment and endpoint verification.
- `source/`: separate source snapshot used as the Docker build context.
- `source/.dockerignore`: excludes secrets, caches and environment files from image build context.
- `nginx.conf`: reverse-proxy configuration, when the application needs a separate proxy.

## Ports
- Application container port: {app_port_label}
- Published host port (default): {host_port}
- Local URL after deployment: `http://localhost:{host_port}`
- Override the published port with `DEPLOYX_HOST_PORT` when running Docker Compose or the Jenkins job.

## Linux deployment
1. Review every generated file and the warnings below.
2. Ensure Linux has Docker Engine, the Docker Compose v2 plugin and permission to access the Docker daemon.
3. From this directory, run `docker compose config -q`.
4. Build with `docker compose build` only after approving execution of repository build steps.
5. Start with `docker compose up -d` only after approving the target host and port.
6. Check with `docker compose ps` and `docker compose logs`.
7. Open `http://localhost:{host_port}` on the deployment host.

## Health verification
- The Jenkins pipeline probes `/` by default and accepts HTTP 2xx or 3xx responses only.
- Set `DEPLOYX_HEALTHCHECK_PATH` in the Jenkins job environment to a project-specific readiness path such as `/health` when the application provides one. The value must begin with `/`.
- The container-level Docker health check for Python and Node.js templates checks whether the application port accepts TCP connections; it is not a substitute for an application-specific readiness endpoint.

## Persistent application storage
{storage_text}
- Storage paths are inferred only from explicit literal Python path assignments and are conservative; review them against application behavior before production use.
- Named volumes are initialized from image directory ownership so the non-root runtime user can write to them. Existing volumes created with incompatible ownership may need a controlled migration.

## Environment variables and secrets
- Secret files such as `.env`, private keys and credential files are not copied into the source snapshot.
- Safe templates such as `.env.example` may be retained in `source/` for review, but all `.env.*` files are excluded from the Docker build context.
- Create a deployment-specific `.env` in this bundle only after reviewing required variables. Do not commit real secrets. Add an explicit Compose `env_file` entry only after reviewing the application configuration.

## Security and review notes
- Generation does not execute application code, build an image or deploy a container.
- Docker builds can execute Dockerfile instructions, dependency installation and package lifecycle/build scripts. Review the source and approve the Jenkins build stage deliberately.
- The Jenkins pipeline requires a Linux agent with Docker access and `curl` installed. It does not automatically remove existing containers or perform rollback.
- The Jenkins endpoint check accepts HTTP 2xx and 3xx responses. HTTP 4xx and 5xx responses are treated as unhealthy.
- Automated rollback is not enabled. If a deployment fails its health check, inspect the logs and recover using your approved release procedure; DeployX does not automatically remove existing containers or restore a previous image.

## Detector warnings
{warning_text}

Generated by DeployX. Review before production use.
'''
    (output / "DEPLOYMENT-README.md").write_text(readme, encoding="utf-8")


def generate_configs(
    project_path: str,
    output_path: str,
    detection: dict[str, Any] | None = None,
    host_port: int | str | None = None,
) -> dict[str, Any]:
    """Generate a deployment bundle outside the source project.

    This function only inspects files and writes a generated bundle. It does
    not execute project code, build containers, or deploy applications.
    """
    requested_output = Path(output_path).expanduser()

    if requested_output.is_symlink():
        raise ValueError("Output directory cannot be a symbolic link.")

    root = Path(project_path).expanduser().resolve()
    output = requested_output.resolve()

    if not root.is_dir():
        raise ValueError("Project directory not found.")

    if output == root or output in root.parents or root in output.parents:
        raise ValueError(
            "Generated output must be separate from the source project and cannot contain it."
        )

    if output.exists() and not output.is_dir():
        raise ValueError("Output path exists but is not a directory.")

    if output.exists() and any(output.iterdir()):
        raise FileExistsError(
            "Generated configuration directory already exists and is not empty. "
            "Review or back up existing files before generating again."
        )

    result = detection if detection is not None else detect_project(str(root))
    if not isinstance(result, dict):
        raise ValueError("Project detection must return a dictionary.")

    project_type = str(result.get("project_type", "unknown"))
    framework = str(result.get("framework", "unknown"))
    warnings: list[str] = []
    is_static = False
    nginx_conf: str | None = None
    app_port: int | None = None
    dockerfile: str
    storage_directories: list[str] = []

    resolved_host_port = _validate_host_port(host_port)

    existing_dockerfile = root / "Dockerfile"
    if existing_dockerfile.is_file():
        warnings.append(
            "An existing Dockerfile was found. The generated Dockerfile is written only into the output bundle; the original project file is not modified. Review differences before using the generated template."
        )

    # ------------------------------------------------------------------
    # Python web applications
    # ------------------------------------------------------------------
    if project_type == "python" and framework in {"Flask", "FastAPI"}:
        entry = result.get("entry_point")
        if not entry:
            raise ValueError("Python entry point could not be detected.")

        module = get_python_module(str(entry))
        storage_directories = detect_persistent_directories(root)
        if storage_directories:
            warnings.append(
                "Persistent application storage paths detected: "
                + ", ".join(storage_directories)
                + ". Review named volume mounts and required data retention before deployment."
            )
        requirements_file = root / "requirements.txt"
        if not requirements_file.is_file():
            warnings.append(
                "requirements.txt is missing. DeployX will install the detected framework runtime, but application-specific dependencies must be added before building."
            )

        if framework == "Flask":
            app_port = 5000
            dockerfile, entry_warning = _python_dockerfile(
                module, framework, app_port, requirements_file.is_file(), storage_directories
            )
        else:
            app_port = 8000
            dockerfile, entry_warning = _python_dockerfile(
                module, framework, app_port, requirements_file.is_file(), storage_directories
            )

        warnings.append(entry_warning)
        upstream = f"app:{app_port}"
        nginx_conf = generate_nginx_config(upstream)

    # ------------------------------------------------------------------
    # Node.js applications
    # ------------------------------------------------------------------
    elif project_type == "nodejs":
        package_file = root / "package.json"
        if not package_file.is_file():
            raise ValueError("Root package.json was not found.")

        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("package.json is invalid or unreadable.") from exc

        if not isinstance(package, dict):
            raise ValueError("package.json must contain a JSON object.")

        scripts = package.get("scripts", {})
        if not isinstance(scripts, dict):
            raise ValueError("package.json scripts must be an object.")

        has_lockfile = (root / "package-lock.json").is_file()
        if not has_lockfile:
            warnings.append(
                "package-lock.json is missing. npm install will be used; commit a lockfile for more reproducible builds."
            )

        if (root / "pnpm-lock.yaml").is_file() or (root / "yarn.lock").is_file():
            warnings.append(
                "A pnpm/yarn lockfile was found, but this generated template uses npm. Review the package manager and lockfile before building."
            )

        # React / Vite frontend
        if framework in {"React", "Vite"}:
            build_script = scripts.get("build", "")
            if not isinstance(build_script, str) or not build_script.strip():
                raise ValueError("React/Vite project has no build script in package.json.")

            is_static = True
            output_dir = "build" if "react-scripts" in build_script else "dist"
            if "vite" not in build_script and "react-scripts" not in build_script:
                warnings.append(
                    "Build output directory is assumed to be dist. Review the framework configuration."
                )

            dockerfile = _frontend_dockerfile(output_dir)
            app_port = 80
            nginx_conf = generate_static_nginx_config(spa_fallback=True)
            warnings.append(
                f"Confirm that the frontend build output is generated in {output_dir}."
            )

        # Express backend
        elif framework == "Express":
            app_port = 3000
            dockerfile = _express_dockerfile(app_port)
            nginx_conf = generate_nginx_config(f"app:{app_port}")

            if "start" not in scripts:
                warnings.append(
                    "package.json has no start script. Confirm that npm start can launch the production server."
                )
            warnings.append(
                "Confirm that the Express server listens on 0.0.0.0:3000 or uses process.env.PORT."
            )
            if "prestart" in scripts:
                warnings.append(
                    "A prestart script is configured. It will execute during container startup; review it before deployment."
                )

        else:
            raise ValueError(
                f"No automatic deployment template is available for {framework} yet."
            )

    # ------------------------------------------------------------------
    # Static websites
    # ------------------------------------------------------------------
    elif project_type == "static":
        is_static = True
        app_port = 80
        dockerfile = _static_dockerfile()
        nginx_conf = generate_static_nginx_config(spa_fallback=False)
        if not (root / "index.html").is_file():
            warnings.append(
                "No root index.html was detected. Confirm the static site entry file and Nginx index configuration before building."
            )

    else:
        raise ValueError(
            f"No safe web deployment template is available for project type: {project_type}."
        )

    if app_port is None:
        raise ValueError("The selected generator did not define an application port.")

    compose = _generate_compose(
        is_static=is_static,
        app_port=app_port,
        host_port=resolved_host_port,
        has_nginx_proxy=bool(nginx_conf),
        storage_directories=storage_directories,
    )

    # Create bundle only after all detection and template checks have passed.
    output.mkdir(parents=True, exist_ok=True)
    source_dir = output / "source"
    copy_summary = copy_project_source(root, source_dir)

    # Preserve an existing Dockerfile in the snapshot before placing the
    # generated proposal at the build-context path. The original project stays
    # untouched, and the previous file remains available for comparison.
    preserved_original_dockerfile = False
    copied_original_dockerfile = source_dir / "Dockerfile"
    if existing_dockerfile.is_file() and copied_original_dockerfile.is_file():
        shutil.copy2(
            copied_original_dockerfile,
            source_dir / "Dockerfile.original",
        )
        preserved_original_dockerfile = True

    # The generated Dockerfile is placed in the bundle and build context only.
    (output / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (source_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")

    generated_files = [
        "Dockerfile",
        "docker-compose.yml",
        "Jenkinsfile",
        "DEPLOYMENT-README.md",
        "source/",
        "source/Dockerfile",
        "source/.dockerignore",
    ]
    if preserved_original_dockerfile:
        generated_files.append("source/Dockerfile.original")

    if nginx_conf:
        (output / "nginx.conf").write_text(nginx_conf, encoding="utf-8")
        generated_files.append("nginx.conf")

    (output / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (output / "Jenkinsfile").write_text(
        _generate_jenkinsfile(resolved_host_port), encoding="utf-8"
    )

    _write_deployment_readme(
        output,
        project_type=project_type,
        framework=framework,
        host_port=resolved_host_port,
        app_port=app_port,
        is_static=is_static,
        warnings=warnings,
        storage_directories=storage_directories,
    )

    return {
        "status": "success",
        "project_type": project_type,
        "framework": framework,
        "generated_files": generated_files,
        "output_directory": str(output),
        "ports": {
            "application_container_port": app_port,
            "published_host_port_default": resolved_host_port,
            "deployment_url": f"http://localhost:{resolved_host_port}",
        },
        "source_copy": copy_summary,
        "persistent_storage": {
            "directories": storage_directories,
            "volumes": [_storage_volume_name(directory) for directory in storage_directories],
        },
        "warnings": warnings,
        "requires_review": True,
        "application_code_executed": False,
        "build_or_deploy_executed": False,
    }


if __name__ == "__main__":
    project = os.environ.get(
        "PROJECT_PATH", "/workspace/Smart-Route-and-Data-Analyzer"
    )
    destination = os.environ.get(
        "GENERATED_CONFIG_PATH", "/artifacts/generated-configs"
    )

    try:
        result = generate_configs(project, destination)
        print(json.dumps(result, indent=2))
    except Exception as error:  # CLI should report an actionable JSON error.
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        raise SystemExit(1)
