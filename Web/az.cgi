#!/bin/bash

export HOME=/var/www/azure; cd

export AZ_DIR=$HOME
export AZURE_CONFIG_DIR=$HOME
export AZURE_CORE_COLLECT_TELEMETRY=0

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then REDIRECT="true" ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then REDIRECT="true" ${0%.*}.py
fi
