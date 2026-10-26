#!/usr/bin/env bash
# Pré-requisitos de compilação no Ubuntu/WSL. Não altera o Python do Windows.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  openjdk-17-jdk-headless zip unzip python3-venv python3-dev \
  build-essential autoconf automake libtool pkg-config cmake ninja-build \
  zlib1g-dev libffi-dev libssl-dev liblzma-dev libsqlite3-dev \
  libncurses5-dev libncursesw5-dev libxslt1.1 ccache patch git curl
