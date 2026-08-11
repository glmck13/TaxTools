#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=$HOME/bin:$PATH

[ "$(echo "$QUERY_STRING" | sed -n 's/.*sandbox=\([^&]*\).*/\1/p')" ] && SANDBOX=true
[[ "$0" == *sandbox* ]] && SANDBOX=true

if [ "$SANDBOX" ]; then
	export QBO_SANDBOX="sandbox-"
	export ADOBE_SANDBOX="sandbox-"
	export PIPELINE_SANDBOX="sandbox-"
fi

qboRefresh.sh >/dev/null
. ${HOME}/etc/${QBO_SANDBOX}qboTokens.conf

adobeRefresh.sh >/dev/null
. ${HOME}/etc/${ADOBE_SANDBOX}adobeTokens.conf

export HOME=/var/www/m365; cd
. ./.bashrc
cd - >/dev/null

export CLIMICROSOFT365_CONFIG_DIR=$HOME

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then ${0%.*}.py
fi
