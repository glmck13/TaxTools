#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

[ "$(echo "$QUERY_STRING" | sed -n 's/.*sandbox=\([^&]*\).*/\1/p')" ] && SANDBOX=true
[[ "$0" == *sandbox* ]] && SANDBOX=true

if [ "$SANDBOX" ]; then
	export SANDBOX
	export QBO_SANDBOX="sandbox-"
	export ADOBE_SANDBOX="sandbox-"
	export PIPELINE_SANDBOX="sandbox-"
fi

qboRefresh.sh >/dev/null
. ${HOME}/etc/${QBO_SANDBOX}qboTokens.conf

adobeRefresh.sh >/dev/null
. ${HOME}/etc/${ADOBE_SANDBOX}adobeTokens.conf

. ${HOME}/etc/resendTokens.conf

export M365_DIR=/var/www/m365
export HOME=$M365_DIR
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export CLIMICROSOFT365_CONFIG_DIR=$HOME

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then REDIRECT="true" ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then REDIRECT="true" ${0%.*}.py
fi
