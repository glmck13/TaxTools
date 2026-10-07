#!/bin/bash

for f in *.pdf
do
	echo $f
	JSON=$(strip.py $f - | extract.py -)
	[ "$JSON" ] || continue
	report.py - -o ${f%.*}.html <<<${JSON}
	jq . >${f%.*}.json <<<${JSON}
done
