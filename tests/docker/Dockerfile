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

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy project
COPY pyproject.toml /opt/ramune-shell/
COPY ramune_shell/ /opt/ramune-shell/ramune_shell/

WORKDIR /opt/ramune-shell
RUN /root/.local/bin/uv sync

EXPOSE 22 9800

CMD ["/bin/sh", "-c", "/usr/sbin/sshd && /root/.local/bin/uv run python -m ramune_shell.worker.main --host 0.0.0.0"]
