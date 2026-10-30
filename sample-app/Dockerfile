
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DISPLAY=:0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tk \
       xvfb \
       x11vnc \
       fluxbox \
       novnc \
       websockify \
       ca-certificates \
       libx11-6 \
       libxext6 \
       libxrender1 \
       libxtst6 \
       libfreetype6 \
       libfontconfig1 \
       fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir numpy matplotlib

WORKDIR /app


COPY entrypoint.sh /app/entrypoint.sh
COPY gui_controller.py /app/gui_controller.py

RUN chmod +x /app/entrypoint.sh

EXPOSE 6081 6082

CMD ["/app/entrypoint.sh"]
