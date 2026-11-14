{% if INCLUDE_WELCOME_LETTER %}

{% if not IS_FULL_AGREEMENT %}
Dear {{GREETING_NAME}},

<b>Happy New Year!</b> We are delighted to continue to have you as our client and look forward to working with you to prepare your tax returns for the {{TAX_YEAR}} tax year.

Included below are links to your tax questionnaire and your SharePoint site for document exchange and storage.

{% set ns = namespace(step=1) %}
{% if SHAREPOINT_FOLDER_URL %}
{{ns.step}}. <a href="{{SHAREPOINT_FOLDER_URL}}" color="#0078d4"><b><u>Your Secure SharePoint Folder</u></b></a><br>Use this main portal folder to securely upload your tax documents, W-2s, 1099s, and supporting records directly to our team.
{% set ns.step = ns.step + 1 %}
{% endif %}
{% if CHECKLIST_FILE_URL %}
{{ns.step}}. <a href="{{CHECKLIST_FILE_URL}}" color="#0078d4"><b><u>Your {{TAX_YEAR}} Tax Document Checklist</u></b></a><br>A customized checklist of the specific tax forms and information statements needed for your return based on prior year filings. This checklist is also included in your SharePoint Folder.
{% set ns.step = ns.step + 1 %}
{% endif %}
{{ns.step}}. <a href="{{QUESTIONNAIRE_FORM_URL}}" color="#0078d4"><b><u>Your {{TAX_YEAR}} Tax Questionnaire</u></b></a><br>Please complete one copy of this Questionnaire and submit to transmit back to us. Please note that for married taxpayers, we only need one questionnaire per household. Also note that if you have already signed an engagement agreement for Services related to your {{TAX_YEAR}} tax return, you may also answer yes to the contracting questions to affirm agreement to the terms.

<br>As a reminder, related to certain data transmittal and data security considerations:

* <b>Note that we do not require written amounts for W-2 wage or Form 1099 investment income or retirement income amounts. Please provide the supporting statements for these items and we will extract the needed information for the returns.</b>

* <b>Please avoid sending any documents</b> containing social security numbers, account information, or personal data <b>BY EMAIL</b>. This is NOT the most secure method for transmitting information. Alternatively, documents may be uploaded to our portal, sent via mail or hand delivered to our office.

We appreciate your business and will be happy to discuss any questions you have regarding this agreement or the charges for our services. Our team looks forward to working with you to lessen the stress involved in preparing your taxes. We wish you a safe, healthy, and prosperous {{NEXT_YEAR}}!

Very truly yours,<br>
<b>Tarrant Advisors</b>

{% elif IS_PAPER %}
<b>Date:</b> {{TODAY_DATE}}<br><b>Client:</b> {{CLIENT_LEGAL_NAME}}<br><b>Address:</b> {{CLIENT_ADDRESS}}{% if CLIENT_PHONE %}<br><b>Phone:</b> {{CLIENT_PHONE}}{% endif %}

Dear {{GREETING_NAME}},

<b>Happy New Year!</b> We are delighted to continue to have you as our client and look forward to working with you to prepare your tax returns for the {{TAX_YEAR}} tax year.

The attached is your {{TAX_YEAR}} tax organizer, tax questionnaire, and the agreement to have Tarrant Advisors prepare your {{TAX_YEAR}} federal and state income tax returns, and where applicable, estimated tax vouchers for {{NEXT_YEAR}}. We also include an engagement agreement which should be completed, signed, and returned to our office with your deposit for Services to be provided. Alternatively, you may agree to the terms of our agreement by checking the appropriate box(s) in the tax questionnaire.

As a reminder, related to certain data transmittal and data security considerations:

* <b>Note that the tax organizer requires similar information as prior years, but we do not require written details of certain W-2 wage or Form 1099 investment income or retirement income amounts. Please provide the supporting statements for these items and we will extract the needed information for the returns.</b>

* <b>Please avoid sending any documents</b> containing social security numbers, account information, or personal data <b>BY EMAIL</b>. This is NOT the most secure method for transmitting information. Alternatively, documents may be uploaded to our portal, sent via mail or hand delivered to our office.

* <font color="#c00000"><b>Effective September 30, 2025, sending CHECKS for tax payments/estimates is no longer the preferred method with the IRS. Although the IRS continues to accept checks, we should convert to electronic payment as soon as possible.</b></font> Paying online is proof of payment, SECURE, and gets recorded to your account immediately. <b>Federal Payments can be made at:</b> <a href="https://www.irs.gov/payments" color="#0078d4"><u>https://www.irs.gov/payments</u></a>. <b>Virginia Payments can be made at:</b> <a href="https://www.tax.virginia.gov/individual-income-tax-payment-options" color="#0078d4"><u>https://www.tax.virginia.gov/individual-income-tax-payment-options</u></a>. Additional states can be searched electronically or let us know and we can provide the information for alternative states.

* <b>Electronic signing</b> provides you the ability to review your tax return online and sign the e-file forms 8879 and State form electronically allowing us to expedite and efficiently process your tax return filings. Once you have reviewed your return, please continue to utilize the electronic signing to allow us to complete the timely transmittal of your returns.

We appreciate your business and will be happy to discuss any questions you have regarding this agreement or the charges for our services. Our team looks forward to working with you to lessen the stress involved in preparing your taxes. We wish you a safe, healthy, and prosperous {{NEXT_YEAR}}!

Very truly yours,<br>
<b>Tarrant Advisors</b>
{% else %}
<b>Date:</b> {{TODAY_DATE}}<br><b>Client:</b> {{CLIENT_LEGAL_NAME}}<br><b>Address:</b> {{CLIENT_ADDRESS}}{% if CLIENT_PHONE %}<br><b>Phone:</b> {{CLIENT_PHONE}}{% endif %}

Dear {{GREETING_NAME}},

<b>Happy New Year!</b> We are delighted to continue to have you as our client and look forward to working with you to prepare your tax returns for the {{TAX_YEAR}} tax year.

Included below are links to your tax questionnaire and your SharePoint site for document exchange and storage.

{% set ns = namespace(step=1) %}
{% if SHAREPOINT_FOLDER_URL %}
{{ns.step}}. <a href="{{SHAREPOINT_FOLDER_URL}}" color="#0078d4"><b><u>Your Secure SharePoint Folder</u></b></a><br>Use this main portal folder to securely upload your tax documents, W-2s, 1099s, and supporting records directly to our team.
{% set ns.step = ns.step + 1 %}
{% endif %}
{% if CHECKLIST_FILE_URL %}
{{ns.step}}. <a href="{{CHECKLIST_FILE_URL}}" color="#0078d4"><b><u>Your {{TAX_YEAR}} Tax Document Checklist</u></b></a><br>A customized checklist of the specific tax forms and information statements needed for your return based on prior year filings. This checklist is also included in your SharePoint Folder.
{% set ns.step = ns.step + 1 %}
{% endif %}
{{ns.step}}. <a href="{{QUESTIONNAIRE_FORM_URL}}" color="#0078d4"><b><u>Your {{TAX_YEAR}} Tax Questionnaire</u></b></a><br>Please complete one copy of this Questionnaire and submit to transmit back to us. Please note that for married taxpayers, we only need one questionnaire per household.

<br>In addition, we include the agreement to have Tarrant Advisors prepare your {{TAX_YEAR}} federal and state income tax returns, and where applicable, estimated tax vouchers for {{NEXT_YEAR}}. Please electronically sign the agreement in the e-signature block below. Note that for married taxpayers, we need the signature of both individuals. Alternatively, you may agree to the terms of our agreement by checking the appropriate box(s) in the tax questionnaire.

As a reminder, related to certain data transmittal and data security considerations:

* <b>Note that we do not require written amounts for W-2 wage or Form 1099 investment income or retirement income amounts. Please provide the supporting statements for these items and we will extract the needed information for the returns.</b>

* <b>Please avoid sending any documents</b> containing social security numbers, account information, or personal data <b>BY EMAIL</b>. This is NOT the most secure method for transmitting information. Alternatively, documents may be uploaded to our portal, sent via mail or hand delivered to our office.

We appreciate your business and will be happy to discuss any questions you have regarding this agreement or the charges for our services. Our team looks forward to working with you to lessen the stress involved in preparing your taxes. We wish you a safe, healthy, and prosperous {{NEXT_YEAR}}!

Very truly yours,<br>
<b>Tarrant Advisors</b>

{% endif %}

{% endif %}

---PAGE_BREAK---
## {{TAX_YEAR}} TAX SERVICES ENGAGEMENT AGREEMENT ("Agreement")

<b>Date:</b> {{TODAY_DATE}}<br><b>Client:</b> {{CLIENT_LEGAL_NAME}}<br><b>Address:</b> {{CLIENT_ADDRESS}}{% if CLIENT_PHONE %}<br><b>Phone:</b> {{CLIENT_PHONE}}{% endif %}

{% if meta_entity_type in ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust', 'organization'] %}

Dear {{GREETING_NAME}}:

Thank you for choosing Tarrant Advisors LLC to provide tax return and tax advisory services (“Services”) for {{CLIENT_LEGAL_NAME}} (“Client”) during the period through June 30, {{NEXT_NEXT_YEAR}}.
{% endif %}

### FEES

Except as requested and specifically agreed upon, we expect the scope of Services and the complexity of your tax returns to be consistent with your prior tax year and related returns:

{{DYNAMIC_ESTIMATES_TABLE}}

### SCOPE OF SERVICES

The Scope of Services is expected to include the following:

{{DYNAMIC_SERVICES_TEXT}}

Tax services in addition to those described above and/or in addition to those provided in the prior year will be charged based on the time incurred at our agreed upon hourly rates:

{% if out_of_scope_items is not none %}
{% if out_of_scope_items|length > 0 %}
{% for item in out_of_scope_items %}
* {{ item }}
{% endfor %}
{% endif %}
{% else %}
{# START_OUT_OF_SCOPE #}
* Additional state returns
* Additional Schedule K-1's or new rental properties or sales
* Detailed estimated payment computations or calculations based on actual activity
* Tax research including analysis of additional transactions
* Detailed correspondence with the tax authorities or audit assistance
{# END_OUT_OF_SCOPE #}
{% endif %}

### TERMS

This document establishes the terms under which Tarrant Advisors LLC will render tax compliance and professional services.

{% if meta_entity_type == 'individual' %}
1. We will prepare your tax returns and voucher estimates and perform tax services ("Services"), as applicable, based only on information you give us. You represent that you will provide us information that is complete, true and accurate, disclosing all relevant facts. We will not verify the information with third parties unless you direct us to. The IRS regulations make it your responsibility to include all income and expenses.
2. You are responsible for making all estimated payments. If requested and agreed to in writing (including email), we will assist with making one Federal estimated payment online and/or provide you with detailed assistance so that you are able to make estimated payments online. Additional fees as described above will apply.
3. You have reviewed our tax organizer including the related questionnaire and completed it to the best of your ability. Attaching and/or enclosing the backup material will be "completing" the organizer. <b><i>You agree to complete the organizer and questionnaire for us to process your returns.</i></b>
4. You agree to provide all needed information with your tax organizer. Please include all W-2's, 1099's and summary year-end statements from your securities accounts and other tax return information, as applicable. Please provide K-1's as soon as received.
5. You agree to respond to our written request for missing information in a timely manner <b>in writing via e-mail, fax or regular mail</b>.
6. <b>You agree to review your returns carefully before signing and submitting Form 8879</b>. We will e-file your returns as soon as possible after receipt of your signed Form 8879. {% if IS_PAPER %}IF YOU ARE RETURNING PAPER COPIES, PLEASE ENSURE SIGNATURES ARE LEGIBLE.{% else %}WE ENCOURAGE THE USE OF ADOBE SIGN FOR EXPEDITING THE REVIEW AND TAX FILING.{% endif %}
7. <b>We do not file extensions unless you ask us to do so. If you want us to file an extension, contact us by April 1st. <i><u>Filing an extension does not relieve you of the obligation to pay all of your taxes by April 15th</u></i></b> (it is an EXTENSION of time to FILE - not an extension of time to PAY). Penalties will apply to any substantial payments made after that date. Extension payments can be made electronically as long as we have your bank information. If your return is extended, you agree to provide all necessary information to complete your return as soon as available but no later than September 15th, or you may be charged additional fees. Final returns are due by October 15th, and it is your responsibility to ensure we have all the required documentation to enable us to prepare and file your returns prior to this deadline.
8. You are aware of IRS record keeping and documentation requirements and represent that you have the necessary records required. We do not audit or verify information, but we may ask for additional clarification.
9. In the event your return is selected for audit, it will be your responsibility to produce documentation, records, and other evidence to substantiate items you claimed as income and/or deductions. We can serve as your representative at our agreed upon hourly rates.
10. You are responsible for penalties on underpayment, late filing, late payment and interest. If you are assessed a penalty because of <b><i>our error</i></b> and we cannot get the penalty abated, we will reimburse you or credit your account at your option for penalties. Generally, interest will not be reimbursed. Any liability of Tarrant Advisors LLC for penalty reimbursement and any other claim related to the Services will be limited to 3 times the fees paid by Client related to the Services performed under this Agreement.
11. We will return all source documents provided to us. We scan and keep copies of most of your supporting documents, but we are not the custodian of your records, and you cannot rely on us to maintain the supporting documents for your tax return; that is your responsibility. By accepting the returns, you acknowledge the return of all original source documents.
12. All invoices rendered for services under the terms of this agreement are <b><u>due upon receipt</u></b>. Final payment is due when you pick up or receive your completed tax returns.
13. Additional tax consulting services including tax planning, tax authority controversy assistance, additional tax return preparation, and other tax services, as requested, will be billed based on the time incurred at our agreed upon hourly rates to range from $100-$325 based on the services performed and the tax professional involved ("agreed upon hourly rates").
14. We attempt to resolve any dispute fairly to all parties. If there should be any unresolved disagreement of any sort, you agree to mediation. If mediation is unsuccessful, you agree to binding arbitration under the rules of the American Arbitration Association. The limit of time for making a claim arising from our services is one year after the services are rendered.
15. If any provision herein is inoperative, the remainder of the agreement shall remain in full force and effect. This agreement is intended as the complete agreement and can only be modified in writing signed by all parties. To the extent that this Agreement is not executed, acceptance and/or filing of the completed tax returns will be deemed agreement to the terms described herein.
{% else %}
1. We will prepare your tax returns and perform tax Services, as applicable, based only on information you provide to us. Client represents that it will provide us with information that is complete, true and accurate, disclosing all relevant facts. We will not verify the information with third parties unless you direct us to. The IRS regulations make it your responsibility to include all income and expenses.
2. Client agrees to provide all needed information required to prepare the returns and provide the Services.
3. Client agrees to respond to our requests for missing information in a timely manner.
4. Client is aware of IRS record keeping and documentation requirements and represents that you have the necessary records required. We do not audit or verify information, but we may ask for additional clarification.
5. In the event your return is selected for audit, it will be your responsibility to produce documentation, records, and other evidence to substantiate items you claimed as income and/or deductions. We can serve as your representative at our agreed upon hourly rates.
6. Client is responsible for penalties on underpayment, late filing, late payment and interest. If you are assessed a penalty because of our error and we cannot get the penalty abated, we will reimburse you or credit your account at your option for penalties. Generally, interest will not be reimbursed. Any liability of Tarrant Advisors for penalty reimbursement and any other claim related to the Services will be limited to 3 times the fees paid by Client related to the Services performed under this Agreement.
7. We will return all source documents provided to us. We scan and keep copies of most of your supporting documents, but we are not the custodian of your records, and you cannot rely on us to maintain the supporting documents for your tax return; that is your responsibility.
8. All invoices rendered for services under the terms of this agreement are due upon receipt. Final payment is due when you pick up or receive your completed tax returns. Invoices unpaid after 30 days will be assessed a 1.5% per month late fee.
9. Additional tax consulting services including tax planning, tax authority controversy assistance, additional tax return preparation and other tax services, as requested, will be billed based on the time incurred at our agreed upon hourly rates to range from $100-$325 based on the services performed and the tax professional involved ("agreed upon hourly rates").
10. We attempt to resolve any dispute fairly to all parties. If there should be any unresolved disagreement of any sort, you agree to mediation. If mediation is unsuccessful, you agree to binding arbitration under the rules of the American Arbitration Association. The time limit for making a claim arising from our services is one year after the services are rendered.
11. If any provision herein is inoperative, the remainder of the agreement shall remain in full force and effect. This agreement is intended as the complete agreement and can only be modified in writing that is signed by all parties.

Thank you for giving Tarrant Advisors the opportunity to serve you. If you have any questions, please call me at (703) 919-2665.
{% endif %}

### Execution and Binding Acceptance

The services and terms described in this agreement are in accordance with my/our understanding and are accepted on behalf of all Taxpayers receiving services:
