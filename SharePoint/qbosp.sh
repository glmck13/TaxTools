#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=:$HOME/bin:$PATH

qboRefresh.sh >/dev/null
. ${HOME}/etc/qboTokens.conf

export M365_DIR=/var/www/m365
export HOME=$M365_DIR
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export CLIMICROSOFT365_CONFIG_DIR=$HOME

export TENANT_URL="https://tarrantadvisors.sharepoint.com"
export SITE_URL="${TENANT_URL}/sites/TarrantAdvisorsShare"
export AUTH_TOKEN=$(m365 util accesstoken get --resource "$TENANT_URL" --output text)

source /var/www/webenv/bin/activate

export GEMINI_API_KEY="AIzaSyAXww-yDVh2G6lhIuMYYFZ0kTO_rSWefVQ"
qbosp.py
