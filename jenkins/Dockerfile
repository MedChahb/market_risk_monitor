# Jenkins controller with Python 3.12 and the pipeline's libraries, installed once at build time.
FROM jenkins/jenkins:2.568.3-lts-jdk21

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=astral/uv:0.13.5 /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python
COPY requirements.txt /tmp/requirements.txt
# unsafe-best-match: torch comes from the PyTorch CPU index, every other package from PyPI
RUN uv venv /opt/venv --python 3.12 \
    && uv pip install --python /opt/venv/bin/python --index-strategy unsafe-best-match -r /tmp/requirements.txt \
    && chown -R jenkins:jenkins /opt/venv /opt/python
ENV PATH=/opt/venv/bin:$PATH

USER jenkins
COPY jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
