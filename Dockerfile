FROM python:3.14-slim-bookworm

LABEL maintainer="Laurent Monin <zas@metabrainz.org>" \
    org.opencontainers.image.title="gitzconsul: git repository to consul kv" \
    org.opencontainers.image.description="Clone a git repo containing json files, and keep a consul kv in sync with it (similar to git2consul)" \
    org.opencontainers.image.authors="Laurent Monin <zas@metabrainz.org>" \
    org.opencontainers.image.vendor="MetaBrainz Foundation" \
    org.opencontainers.image.documentation="https://github.com/metabrainz/gitzconsul/blob/main/README.md"

ENV \
  # python:
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PYTHONDONTWRITEBYTECODE=1 \
  # pip:
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# System deps:
RUN apt-get update \
  && apt-get install --no-install-recommends -y \
    bash \
    curl \
    git \
    openssh-client \
    ca-certificates \
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# install gosu
ARG GOSU_VERSION=1.17
ARG GOSU_PATH=/usr/local/bin/gosu
RUN dpkgArch="$(dpkg --print-architecture | awk -F- '{ print $NF }')" \
 && echo "Downloading gosu $GOSU_VERSION-$dpkgArch -> $GOSU_PATH" \
 && curl --location --output "$GOSU_PATH" "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-$dpkgArch" \
 && chmod +x "$GOSU_PATH" \
 && gosu nobody true

WORKDIR /code
COPY . /code/

RUN uv sync --frozen --no-dev --no-editable

ARG USER_ID=61000
ARG USER_GROUP_ID=61000
ARG USER_NAME=gitzconsul
ARG USER_GROUP=${USER_NAME}
ARG USER_HOME=/home/${USER_NAME}

ENV USER_ID=$USER_ID
ENV USER_GROUP_ID=$USER_GROUP_ID
ENV USER_NAME=$USER_NAME
ENV USER_GROUP=$USER_GROUP
ENV USER_HOME=$USER_HOME

# To create the key:
# ssh-keygen -t ed25519 -C 'gitzconsul' -P '' -f ./id_rsa_shared
# use docker run option:
# --volume $(pwd)/id_rsa_shared:/tmp/.ssh/id_rsa_shared:ro

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
