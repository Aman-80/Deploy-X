
import json
import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


WORKSPACE = "/workspace"
ARTIFACT_DIR = "/artifacts"
MAX_REQUEST_SIZE = 16384


def send_json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class WorkerHandler(BaseHTTPRequestHandler):

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))

        if length < 1 or length > MAX_REQUEST_SIZE:
            raise ValueError("Invalid request size.")

        data = json.loads(self.rfile.read(length))

        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")

        return data

    def get_repository_path(self, repo_name):
        if (
            not isinstance(repo_name, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repo_name)
            or repo_name in {".", ".."}
        ):
            return None

        workspace = os.path.realpath(WORKSPACE)
        candidate = os.path.join(workspace, repo_name)
        project_path = os.path.realpath(candidate)

        if (
            os.path.islink(candidate)
            or os.path.commonpath([workspace, project_path]) != workspace
            or not os.path.isdir(project_path)
            or not os.path.isdir(os.path.join(project_path, ".git"))
        ):
            return None

        return project_path

    def do_GET(self):
        route = urlparse(self.path).path

        if route == "/health":
            send_json(
                self,
                200,
                {"status": "healthy", "worker": "DeployX"}
            )
        else:
            send_json(self, 404, {"error": "Endpoint not found."})

    def do_POST(self):
        route = urlparse(self.path).path

        if route == "/test":
            self.handle_project_test()
            return

        if route == "/build":
            self.handle_project_build()
            return

        if route == "/checkout":
            self.handle_checkout()
            return

        send_json(self, 404, {"error": "Endpoint not found."})

    def handle_checkout(self):
        try:
            data = self.read_json_body()
            url = data.get("url", "")
            branch = data.get("branch", "main")

            if not isinstance(url, str) or not isinstance(branch, str):
                send_json(self, 400, {
                    "error": "Repository URL and branch must be strings."
                })
                return

            url = url.strip().rstrip("/")
            branch = branch.strip()

            parsed = urlparse(url)
            parts = parsed.path.strip("/").split("/")

            valid_url = (
                parsed.scheme == "https"
                and parsed.netloc.lower() == "github.com"
                and len(parts) == 2
                and all(
                    re.fullmatch(
                        r"[A-Za-z0-9-]+",
                        part.removesuffix(".git")
                    )
                    for part in parts
                )
            )

            if not valid_url:
                send_json(self, 400, {
                    "error": "Invalid HTTPS GitHub repository URL."
                })
                return

            if (
                not branch
                or len(branch) > 100
                or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)
            ):
                send_json(self, 400, {"error": "Invalid branch name."})
                return

            env = os.environ.copy()
            env["REPOSITORY_URL"] = url
            env["REPOSITORY_BRANCH"] = branch

            result = subprocess.run(
                ["python", "/pipeline/checkout.py"],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            if result.returncode != 0:
                send_json(self, 409, {
                    "error": "Checkout failed.",
                    "details": (result.stderr or result.stdout)[-2000:]
                })
                return

            repo_name = parts[1].removesuffix(".git")

            send_json(self, 200, {
                "status": "success",
                "repository": repo_name,
                "branch": branch,
                "message": "Repository checkout completed."
            })

        except subprocess.TimeoutExpired:
            send_json(self, 504, {"error": "Checkout timed out."})

        except (ValueError, UnicodeDecodeError):
            send_json(self, 400, {"error": "Invalid JSON request."})

        except Exception:
            send_json(self, 500, {"error": "Worker request failed."})

    def handle_project_test(self):
        try:
            data = self.read_json_body()
            repo_name = data.get("repository", "")
            project_path = self.get_repository_path(repo_name)

            if project_path is None:
                send_json(self, 404, {
                    "error": "Valid Git repository not found in persistent storage."
                })
                return

            env = os.environ.copy()
            env["PROJECT_PATH"] = project_path

            result = subprocess.run(
                ["python", "/pipeline/test_project.py"],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            try:
                output = json.loads(result.stdout)
            except (ValueError, TypeError):
                send_json(self, 500, {
                    "error": "Project validator returned invalid output.",
                    "details": (result.stderr or result.stdout)[-2000:]
                })
                return

            send_json(
                self,
                200 if result.returncode == 0 else 422,
                output
            )

        except subprocess.TimeoutExpired:
            send_json(self, 504, {
                "error": "Project validation timed out."
            })

        except (ValueError, UnicodeDecodeError):
            send_json(self, 400, {"error": "Invalid JSON request."})

        except Exception:
            send_json(self, 500, {
                "error": "Project validation failed."
            })

    def handle_project_build(self):
        try:
            data = self.read_json_body()
            repo_name = data.get("repository", "")
            project_path = self.get_repository_path(repo_name)

            if project_path is None:
                send_json(self, 404, {
                    "error": "Valid Git repository not found in persistent storage."
                })
                return

            if not os.path.isdir(ARTIFACT_DIR):
                send_json(self, 500, {
                    "error": "Persistent artifact storage is unavailable."
                })
                return

            env = os.environ.copy()
            env["PROJECT_PATH"] = project_path

            result = subprocess.run(
                ["python", "/pipeline/build_project.py"],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            try:
                output = json.loads(result.stdout)
            except (ValueError, TypeError):
                send_json(self, 500, {
                    "error": "Build script returned invalid output.",
                    "details": (result.stderr or result.stdout)[-2000:]
                })
                return

            successful = (
                result.returncode == 0
                and output.get("status") == "success"
            )

            if successful:
                artifact_name = output.get("artifact", "")
                artifact_path = os.path.realpath(
                    os.path.join(ARTIFACT_DIR, artifact_name)
                )
                artifact_root = os.path.realpath(ARTIFACT_DIR)

                if (
                    not artifact_name
                    or os.path.commonpath(
                        [artifact_root, artifact_path]
                    ) != artifact_root
                    or not os.path.isfile(artifact_path)
                    or os.path.islink(artifact_path)
                ):
                    send_json(self, 500, {
                        "error": "Build artifact was not found in artifact storage."
                    })
                    return

            send_json(
                self,
                200 if successful else 422,
                output
            )

        except subprocess.TimeoutExpired:
            send_json(self, 504, {"error": "Build timed out."})

        except (ValueError, UnicodeDecodeError):
            send_json(self, 400, {"error": "Invalid JSON request."})

        except Exception:
            send_json(self, 500, {"error": "Project build failed."})

    def log_message(self, format_string, *args):
        print("DeployX worker:", format_string % args)


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("0.0.0.0", 8000),
        WorkerHandler
    )
    print("DeployX worker API listening on port 8000")
    server.serve_forever()
