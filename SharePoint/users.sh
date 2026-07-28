#!/bin/bash

site=${1:?Enter site name}

m365 spo user list --webUrl "/sites/$site" $M365OPTS
