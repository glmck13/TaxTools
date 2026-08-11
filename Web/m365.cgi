#!/bin/bash

export HOME=/var/www/m365; cd
. ./.bashrc
cd - >/dev/null

export CLIMICROSOFT365_CONFIG_DIR=$HOME

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then ${0%.*}.py
fi
