#!/bin/bash

export M365_DIR=/var/www/m365
export HOME=$M365_DIR
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm  
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
export CLIMICROSOFT365_CONFIG_DIR=$HOME

[ "$VIRTUAL_ENV" ] || source /var/www/webenv/bin/activate

if [ -x ${0%.*}.sh ]; then ${0%.*}.sh
elif [ -x ${0%.*}.py ]; then ${0%.*}.py
fi
