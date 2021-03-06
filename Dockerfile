FROM python:3.8-slim-buster

ENV \
  # python:
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PYTHONDONTWRITEBYTECODE=1 \
  # pip:
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100 \
  # poetry:
  POETRY_VERSION=1.1.4 \
  POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_CREATE=false \
  POETRY_CACHE_DIR='/var/cache/pypoetry' \
  PATH="$PATH:/root/.poetry/bin"

# System deps:
RUN apt-get update \
  && apt-get install --no-install-recommends -y \
    bash \
    curl \
    git \
    openssh-client \
    ca-certificates \
  # Installing `poetry` package manager:
  # https://github.com/python-poetry/poetry
  && curl -sSL 'https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py' | python \
  && poetry --version \
  # Cleaning cache:
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# install gosu
ARG GOSU_VERSION=1.12
RUN dpkgArch="$(dpkg --print-architecture | awk -F- '{ print $NF }')" \
 && curl --location --output /usr/local/bin/gosu "https://github.com/tianon/gosu/releases/download/$GOSU_VERSION/gosu-$dpkgArch" \
 && chmod +x /usr/local/bin/gosu \
 && gosu nobody true

WORKDIR /code
COPY . /code/
RUN poetry install --no-interaction --no-ansi --no-dev

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
