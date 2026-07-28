PURGE=$1

#
# Azure
#
for f in \
az_logout.cgi \
az_poll.cgi \
az_start.cgi \
az_status.cgi \
az_taxqanda.cgi \
az_taxquestionnaire.cgi \
; do
	rm -f $f
	[ "$PURGE" ] || ln az.cgi $f
done

#
# M365
#
for f in \
m365_actionitems.cgi \
m365_dashboard.cgi \
m365_logout.cgi \
m365_pdfunite.cgi \
m365_poll.cgi \
m365_start.cgi \
m365_status.cgi \
nph-m365.cgi \
nph-m365_convert2pdf.cgi \
nph-m365_intake.cgi \
nph-m365_outlook.cgi \
; do
	rm -f $f
	[ "$PURGE" ] || ln m365.cgi $f
done

#
# QBO
#
for f in \
nph-qbo.cgi \
nph-qbo_intake.cgi \
engagement_pipeline.cgi \
; do
	rm -f $f
	[ "$PURGE" ] || ln qbo.cgi $f
done
