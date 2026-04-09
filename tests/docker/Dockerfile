FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    openssh-server \
    curl \
    && rm -rf /var/lib/apt/lists/*

# SSH setup
RUN mkdir /run/sshd
RUN echo 'root:testpass' | chpasswd
RUN sed -i 's/#PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config
RUN sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config

# Install uv + Python
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy project
COPY pyproject.toml /opt/ramune-shell/
COPY protocol/ /opt/ramune-shell/protocol/
COPY worker/ /opt/ramune-shell/worker/
COPY plugins/ /opt/ramune-shell/plugins/

# Worker-only pyproject (no mcp dependency)
RUN echo '[project]\n\
name = "ramune-shell-test"\n\
version = "0.1.0"\n\
requires-python = ">=3.11"\n\
\n\
[tool.uv.workspace]\n\
members = ["worker", "protocol"]\n\
\n\
[dependency-groups]\n\
dev = ["ramune-shell-worker"]\n\
\n\
[tool.uv.sources]\n\
ramune-shell-worker = { workspace = true }' > /opt/ramune-shell/pyproject.toml

# Install deps and worker
WORKDIR /opt/ramune-shell
RUN /root/.local/bin/uv sync

EXPOSE 22 9800

# Start SSH + worker
CMD /usr/sbin/sshd && /root/.local/bin/uv run python -m ramune_shell_worker.main --host 0.0.0.0
