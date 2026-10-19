FROM ubuntu:24.04
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends python3 git zsh tmux curl ca-certificates shellcheck \
    && rm -rf /var/lib/apt/lists/*
RUN sh -c "$(curl -fsLS get.chezmoi.io)" -- -b /usr/local/bin
WORKDIR /work
CMD ["python3", "-m", "unittest", "discover", "-s", "tests", "-v"]
