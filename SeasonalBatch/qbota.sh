#!/bin/bash

export HOME=/var/www/tarrantadvisors
export PATH=.:$HOME/bin:$PATH

TOKENFILE=/var/www/etc/qboTokens.conf
qboRefresh.sh >/dev/null
. $TOKENFILE

source /var/www/webenv/bin/activate

qbota.py $*
