#!/bin/bash

case "$1" in
	az|gem|diy)
		model=$1
		shift 1
		;;
	*)
		echo "Enter model: {az|gem|diy}"
		exit
		;;
esac

for f in $*
do
	echo $f
	s=${f%.pdf}-scheds.pdf
	strip.py $f $s
	[ -f $s ] || continue
	JSON=$(${model}extract.py $s)
	[ "$JSON" ] || continue
	report.py - -o ${f%.*}.html <<<${JSON}
	jq . >${f%.*}.json <<<${JSON}
done
