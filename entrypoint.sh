#!/bin/sh
set -e

# NOTE: $USER_* env vars are passed via Dockerfile ENV
getent group "$USER_GROUP"  >/dev/null 2>&1 || \
  groupadd --gid "$USER_GROUP_ID" "$USER_GROUP"

id -u "$USER_NAME" >/dev/null 2>&1 || \
  useradd --uid "$USER_ID" --gid "$USER_GROUP" --shell /bin/bash \
	--no-log-init --system --create-home --home-dir "$USER_HOME" "$USER_NAME"

mkdir -p "${USER_HOME}/.ssh"
chmod 700 "$USER_HOME/.ssh"

if [ -f /tmp/.ssh/id_rsa_shared ]; then
	cp -v /tmp/.ssh/id_rsa_shared "$USER_HOME/.ssh/id_rsa"
	chmod 600 "$USER_HOME/.ssh/id_rsa"
fi
if [ -f /tmp/.ssh/config ]; then
	cp -v /tmp/.ssh/config "$USER_HOME/.ssh/"
fi
if [ -f /tmp/.ssh/known_hosts ]; then
	cp -v /tmp/.ssh/known_hosts "$USER_HOME/.ssh/"
else
	ssh-keyscan -H github.com >> "$USER_HOME/.ssh/known_hosts" 2>/dev/null
fi

chown -R "$USER_NAME:$USER_GROUP" "$USER_HOME/.ssh"
# following line can be used to test ssh connection
#exec gosu "$USER_NAME" ssh -Tvvv git@github.com
exec gosu "$USER_NAME" gitzconsul "$@"
