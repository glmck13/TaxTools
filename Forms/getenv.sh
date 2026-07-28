#!/bin/bash

az login --allow-no-subscriptions
export TOKEN=$(az account get-access-token --resource https://forms.office.com --query accessToken --output tsv)
export TENANT=$(az account show --query tenantId -o tsv)
export USERID=$(az ad signed-in-user show --query id -o tsv)

echo TENANT=$TENANT
echo USERID=$USERID
echo TOKEN=$TOKEN
