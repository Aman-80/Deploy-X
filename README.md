# DeployX — Smart CI/CD & Deployment Platform

DeployX is a Docker-based DevOps mini-project designed to automate repository processing, project detection, testing, build artifact generation, sample application deployment, and Docker container monitoring.

It uses a modular architecture with a Flask web application, separate pipeline workers, persistent Docker volumes, and an Nginx monitoring gateway.

## 1. Project Overview

DeployX provides a web dashboard to manage a basic CI/CD workflow:

1. Register a GitHub repository.
2. Detect the project's technology and structure.
3. Check out repository source code.
4. Run automated source-level checks.
5. Generate downloadable build artifacts.
6. Deploy the supported sample Python GUI application.
7. Monitor Docker containers through a read-only API.

## 2. Technology Stack

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| Containerization | Docker, Docker Compose |
| Pipeline | Python worker services |
| Reverse proxy | Nginx |
| Container monitoring | Docker Socket Proxy |
| GUI deployment | Tkinter, Xvfb, noVNC |
| Version control | Git, GitHub |

## 3. Architecture

```text
                 User / Browser
                       |
                       v
              DeployX Web Dashboard
                 Flask Application
                  Port 5001
                       |
          +------------+------------+
          |            |            |
          v            v            v
      SQLite DB    Worker API    Monitoring
                    Port 8000      Gateway
                                      |
                                      v
                              Docker Socket Proxy
                                      |
                                      v
                                Docker Engine

          Pipeline Worker
                |
                v
       Repository Processing
                |
                v
        Build ZIP Artifacts
                |
                v
         GUI Deployment
                |
                v
       Tkinter + noVNC Console
             Port 6081
```

## 4. Main Features

### Repository Management
- Register GitHub repositories.
- Validate repository URLs.
- Detect project files and technology.
- Store registered repository information.

### CI/CD Pipeline
- Repository checkout through a separate worker.
- Python source and project configuration checks.
- Build ZIP artifacts.
- Record pipeline execution history and status.
- Download generated artifacts.

### Application Deployment
- Separate GUI deployment controller.
- Persistent application workspace.
- Browser-based access to the supported Tkinter sample application using noVNC.

### Docker Container Monitoring
- Retrieve Docker container information.
- Display container names, IDs and images.
- Show running and stopped states.
- Display container status and port information.
- Manually refresh monitoring information.

The monitoring interface is read-only. Container start, stop and deletion controls are not implemented.

## 5. Docker Services

| Service | Purpose |
|---|---|
| deployx-app | Flask dashboard and REST API |
| deployx-worker-api | Repository pipeline operations |
| deployx-worker | Optional pipeline worker |
| deployx-gui | GUI deployment and browser access |
| docker-socket-proxy | Restricted Docker API access |
| docker-monitoring-gateway | Nginx monitoring gateway |

## 6. Network Ports

| Port | Service | Access |
|---|---|---|
| 5001 | DeployX Web Dashboard | Host |
| 6081 | GUI / noVNC | Localhost only |
| 8000 | Worker API | Internal Docker network |
| 2375 | Docker Socket Proxy | Internal Docker network |
| 8080 | Monitoring Gateway | Internal Docker network |

**Important:** Monitoring Gateway port 8080 is not published to the host. It does not conflict with an independently running Jenkins service using host port 8080.

## 7. Installation and Setup

### Requirements

- Docker Desktop
- Docker Compose plugin
- Git
- Modern web browser

Python does not need to be installed separately on the host for the Docker-based setup.

### Step 1: Clone the Repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd DeployX
```

### Step 2: Validate Docker Configuration

```bash
docker compose config
```

### Step 3: Build and Start Services

```bash
docker compose up -d --build
```

### Step 4: Check Running Services

```bash
docker compose ps -a
```

### Step 5: Open DeployX

Dashboard:

```text
http://localhost:5001
```

GUI Console:

```text
http://127.0.0.1:6081/vnc.html
```

## 8. Useful Docker Commands

View service status:

```bash
docker compose ps
```

View application logs:

```bash
docker compose logs -f deployx-app
```

View worker logs:

```bash
docker compose logs -f deployx-worker-api
```

Restart the application:

```bash
docker compose restart deployx-app
```

Stop project services:

```bash
docker compose down
```

The named Docker volumes preserve application data when services are stopped or containers are removed. Avoid `docker compose down -v` unless you intentionally want to delete project volumes and their stored data.

## 9. Persistent Storage

DeployX uses Docker named volumes:

| Volume | Purpose |
|---|---|
| deployx-data | SQLite database |
| deployx-repos | Checked-out repositories |
| deployx-artifacts | Generated ZIP artifacts |
| deployx-gui-data | GUI application workspace |

## 10. Project Directory Structure

```text
DeployX/
│
├── app/
│   ├── app.py
│   ├── requirements.txt
│   └── templates/
│       └── index.html
│
├── pipeline/
│   ├── checkout.py
│   ├── detect_project.py
│   ├── test_project.py
│   ├── build_project.py
│   ├── worker_api.py
│   └── Dockerfile
│
├── sample-app/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   └── gui_controller.py
│
├── monitoring/
│   └── nginx.conf
│
├── jenkins/
├── nginx/
├── docs/
│
├── Dockerfile
├── docker-compose.yml
└── .gitignore
```

## 11. Security and Design Considerations

- Docker API access is routed through a dedicated socket proxy.
- Docker proxy POST operations are disabled.
- The Nginx gateway restricts the application-facing monitoring endpoint to container listing and health checks.
- Monitoring and Docker backend networks are internal Docker networks.
- The GUI console is bound to localhost.
- Repository and artifact volumes are mounted read-only where application access does not require write permissions.

DeployX is currently a local development and demonstration project. Additional authentication, production security hardening, and deployment capabilities would be required before production use.

## 12. Current Project Scope and Limitations

- Project detection identifies supported source files and project structure.
- Current testing includes source-level checks; it is not a complete test suite for every application framework.
- Build generation produces ZIP artifacts.
- The current GUI deployment demonstration targets the supported Python/Tkinter sample application.
- Docker monitoring provides container inventory and status information, not full CPU and memory metrics.
- The monitoring dashboard does not provide container control operations.

## 13. Future Enhancements

- Advanced CPU and memory monitoring.
- Automated monitoring refresh and filtering.
- More application deployment targets.
- Enhanced security scanning.
- Deployment rollback support.
- Extended CI/CD integrations.

## 14. Project Purpose

DeployX demonstrates practical knowledge of Python backend development, Docker containerization, CI/CD automation, repository processing, service isolation, persistent storage, Nginx configuration, and Docker API integration.

It was developed as a hands-on MCA Cloud Computing and DevOps project.

---

**DeployX — Automating the Journey from Repository to Deployment.**