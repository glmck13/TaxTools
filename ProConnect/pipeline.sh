#!/bin/bash

for f in $*
do
	echo $f
	s=${f%.pdf}-scheds.pdf
	strip.py $f $s
	[ -f $s ] || continue
	JSON=$(extract.py $s)
	[ "$JSON" ] || continue
	report.py - -o ${f%.*}.html <<<${JSON}
	jq . >${f%.*}.json <<<${JSON}
done
