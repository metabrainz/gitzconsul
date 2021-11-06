#!/bin/bash

if [ ! -z "$1" ]; then
	CONSUL_IMAGE_VERSION=$1
else
	CONSUL_IMAGE_VERSION=latest
fi

IMAGE=library/consul:$CONSUL_IMAGE_VERSION

CONTAINER_NAME=dev-consul
docker rm -f $CONTAINER_NAME

#note: enable_script_checks for testing only, unsecure
docker run -d --name=$CONTAINER_NAME -e CONSUL_BIND_INTERFACE=lo -v /var/run/docker.sock:/var/run/docker.sock --net=host $IMAGE
