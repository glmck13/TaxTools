#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

TOKENFILE=/var/www/etc/qboTokens.conf
qboRefresh.sh >/dev/null
. $TOKENFILE

export HOME=/var/www/m365; cd
. ./.bashrc
cd - >/dev/null

export CLIMICROSOFT365_CONFIG_DIR=$HOME

export TENANT_URL="https://tarrantadvisors.sharepoint.com"
export SITE_URL="${TENANT_URL}/sites/TarrantAdvisorsShare"
export AUTH_TOKEN=$(m365 util accesstoken get --resource "$TENANT_URL" --output text)

source /var/www/webenv/bin/activate

cd /tmp
export GEMINI_API_KEY=
qbosp.py
