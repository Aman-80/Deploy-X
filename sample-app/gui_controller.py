
import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ARTIFACT_DIR = "/artifacts"
PROJECT_DIR = "/app/project"
APP_PATH = os.path.join(PROJECT_DIR, "Smart_Route_Analyzer.py")
LOG_PATH = "/tmp/smart-route-app.log"
MAX_REQUEST_SIZE = 4096
MAX_ARTIFACT_SIZE = 25 * 1024 * 1024
MAX_SOURCE_SIZE = 5 * 1024 * 1024

app_process = None
deploy_lock = threading.RLock()


def send_json(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def read_app_log():
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as log:
            return log.read()[-3000:]
    except OSError:
        return ""


def start_gui():
    os.makedirs(PROJECT_DIR, exist_ok=True)

    with open(LOG_PATH, "a", encoding="utf-8") as log:
        return subprocess.Popen(
            [sys.executable, APP_PATH],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            start_new_session=True,
        )


def stop_gui():
    global app_process

    if app_process is not None and app_process.poll() is None:
        app_process.terminate()

        try:
            app_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app_process.kill()
            app_process.wait(timeout=5)

    app_process = None


def deploy_artifact(artifact_name):
    global app_process

    if (
        not isinstance(artifact_name, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}\.zip",
            artifact_name
        )
    ):
        return 400, {"error": "Invalid artifact filename."}

    artifact_path = os.path.join(ARTIFACT_DIR, artifact_name)

    if os.path.islink(artifact_path) or not os.path.isfile(artifact_path):
        return 404, {"error": "Artifact not found."}

    if os.path.getsize(artifact_path) > MAX_ARTIFACT_SIZE:
        return 413, {"error": "Artifact exceeds the size limit."}

    try:
        with zipfile.ZipFile(artifact_path, "r") as archive:
            try:
                member = archive.getinfo("Smart_Route_Analyzer.py")
            except KeyError:
                return 422, {
                    "error": "Artifact does not contain Smart_Route_Analyzer.py."
                }

            if (
                member.file_size < 1
                or member.file_size > MAX_SOURCE_SIZE
                or member.is_dir()
            ):
                return 422, {"error": "Source file has an invalid size."}

            source = archive.read(member)

        source_text = source.decode("utf-8")
        ast.parse(source_text, filename="Smart_Route_Analyzer.py")

    except (zipfile.BadZipFile, UnicodeDecodeError, SyntaxError, OSError):
        return 422, {
            "error": "Artifact is invalid or Python syntax validation failed."
        }

    with deploy_lock:
        previous_source = None

        if os.path.isfile(APP_PATH):
            with open(APP_PATH, "rb") as existing:
                previous_source = existing.read()

        stop_gui()

        temporary_path = APP_PATH + ".new"

        try:
            with open(temporary_path, "wb") as new_file:
                new_file.write(source)

            os.replace(temporary_path, APP_PATH)
            app_process = start_gui()

            time.sleep(2)

            if app_process.poll() is not None:
                startup_log = read_app_log()
                stop_gui()

                if previous_source is not None:
                    with open(temporary_path, "wb") as old_file:
                        old_file.write(previous_source)
                    os.replace(temporary_path, APP_PATH)
                    app_process = start_gui()
                else:
                    app_process = None

                return 422, {
                    "error": "New application exited during startup.",
                    "rollback_attempted": previous_source is not None,
                    "details": startup_log,
                }

            return 200, {
                "status": "deployed",
                "application": "Smart Route and Data Analyzer",
                "artifact": artifact_name,
                "message": "Application started from the selected ZIP artifact.",
                "pid": app_process.pid,
            }

        except OSError as error:
            try:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)

                if previous_source is not None:
                    with open(APP_PATH, "wb") as existing:
                        existing.write(previous_source)

                app_process = start_gui() if previous_source is not None else None

            except OSError:
                app_process = None

            return 500, {
                "error": "Could not update the deployed application.",
                "details": str(error),
            }


class ControllerHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path != "/health":
            send_json(self, 404, {"error": "Endpoint not found."})
            return

        running = app_process is not None and app_process.poll() is None

        send_json(self, 200 if running else 503, {
            "controller": "DeployX GUI",
            "status": "running" if running else "degraded",
            "application_pid": app_process.pid if running else None,
        })

    def do_POST(self):
        if self.path != "/deploy":
            send_json(self, 404, {"error": "Endpoint not found."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))

            if length < 1 or length > MAX_REQUEST_SIZE:
                send_json(self, 400, {"error": "Invalid request size."})
                return

            data = json.loads(self.rfile.read(length))

            if not isinstance(data, dict):
                send_json(self, 400, {
                    "error": "Request body must be a JSON object."
                })
                return

            status, result = deploy_artifact(data.get("artifact"))
            send_json(self, status, result)

        except (ValueError, UnicodeDecodeError):
            send_json(self, 400, {"error": "Invalid JSON request."})

        except Exception:
            send_json(self, 500, {"error": "Deployment request failed."})

    def log_message(self, format_string, *args):
        print("DeployX GUI controller:", format_string % args)


if __name__ == "__main__":
    os.makedirs(PROJECT_DIR, exist_ok=True)

    if not os.path.isfile(APP_PATH):
        print("ERROR: Application source file is missing.", file=sys.stderr)
        sys.exit(1)

    app_process = start_gui()

    time.sleep(2)

    if app_process.poll() is not None:
        print("ERROR: Initial GUI application failed to start.", file=sys.stderr)
        print(read_app_log(), file=sys.stderr)
        sys.exit(1)

    server = ThreadingHTTPServer(("0.0.0.0", 6082), ControllerHandler)
    print("DeployX GUI controller listening on internal port 6082")

    try:
        server.serve_forever()
    finally:
        server.server_close()
        stop_gui()
