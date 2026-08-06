# Tarrant Advisors LLC
1875 Campus Commons Dr., Suite 203, Reston, VA 20191  
75 Port City Landing, Suite 110, Mt. Pleasant, SC 29464  

## {{TAX_YEAR}} TAX SERVICES ENGAGEMENT AGREEMENT ("Agreement")

<b>Date:</b> {{TODAY_DATE}}<br><b>Client:</b> {{CLIENT_LEGAL_NAME}}<br><b>Address:</b> {{CLIENT_ADDRESS}}  

{% if meta_entity_type in ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust', 'organization'] %}
<br/>
<br/>
<br/>
Dear {{ GREETING_NAME }}:<br/>
Thank you for choosing Tarrant Advisors LLC to provide tax return and tax advisory services (“Services”) for {{ CLIENT_LEGAL_NAME }} (“Client”) during the period through December 31, {{ NEXT_YEAR }}.
{% endif %}

### FEES

Except as requested and specifically agreed upon, we expect the scope of Services and the complexity of your tax returns to be consistent with your prior tax year and related returns:

{{DYNAMIC_ESTIMATES_TABLE}}

### SCOPE OF SERVICES

The Scope of Services is expected to include the following:

{{DYNAMIC_SERVICES_TEXT}}

Tax services in addition to those described above and/or in addition to those provided in the prior year will be charged based on the time incurred at our agreed upon hourly rates:
{% if out_of_scope_items %}
{% for item in out_of_scope_items %}
* {{ item }}
{% endfor %}
{% else %}
* Additional state returns
* Additional Schedule K-1's or new rental properties or sales
* Detailed estimated payment computations or calculations based on actual activity
* Tax research including analysis of additional transactions
* Detailed correspondence with the tax authorities or audit assistance
{% endif %}

### TERMS

This document establishes the terms under which Tarrant Advisors LLC will render tax compliance and professional services. 

{% if meta_entity_type == 'individual' %}
1. We will prepare your tax returns and voucher estimates and perform tax services ("Services"), as applicable, based only on information you give us. You represent that you will provide us information that is complete, true and accurate, disclosing all relevant facts. We will not verify the information with third parties unless you direct us too. The IRS regulations makes it your responsibility to include all income and expenses.
2. You are responsible for making all estimated payments. If requested and agreed to in writing (including email), we will assist with the making one Federal estimated payment online and/or provide you with detailed assistance so that you are able to make estimated payments online. Additional fees as described above will apply. 
3. You have reviewed our tax organizer including the related questionnaire and completed it to the best of your ability. Attaching and/or enclosing the backup material will be "completing" the organizer. <b><i>You agree to complete the organizer and questionnaire for us to process your returns.</i></b>
4. You agree to provide all needed information with your tax organizer. Please include all W-2's, 1099's and summary year end statements from your securities accounts and other tax return information, as applicable. Please provide K-1's as soon as received. 
5. You agree to respond to our written request for missing information in a timely manner <b>in writing via e-mail, fax or regular mail</b>.
6. <b>You agree to review your returns carefully before signing and submitting Form 8879</b>. We will e-file your returns as soon as possible after receipt of your signed Form 8879. WE ENCOURAGE THE USE OF ADOBE SIGN FOR EXPEDITING THE REVIEW AND TAX FILING.
7. <b>We do not file extensions unless you ask us to do so. If you want us to file an extension, contact us by April 1, 2027. <i><u>Filing an extension does not relieve you of the obligation to pay all of your taxes by April 15, 2027</u></i></b> (it is an EXTENSION of time to FILE - not an extension of time to PAY). Penalties will apply to any substantial payments made after that date. Extension payments can be made electronically as long as we have your bank information. If your return is extended, you agree to provide all necessary information to complete your return as soon as available but no later than September 1, 2026, or you may be charged additional fees. Final returns are due by October 15th, and it is your responsibility to ensure we have all the required documentation to enable us to prepare and file your returns prior to this deadline.
8. You are aware of IRS record keeping and documentation requirements and represent that you have the necessary records required. We do not audit or verify information, but we may ask for additional clarification.
9. In the event your return is selected for audit, it will be your responsibility to produce documentation, records, and other evidence to substantiate items you claimed as income and/or deductions. We can serve as your representative at our agreed upon hourly rates.
10. You are responsible for penalties on underpayment, late filing, late payment and interest. If you are assessed a penalty because of <b><i>our error</i></b> and we cannot get the penalty abated, we will reimburse you or credit your account at your option for penalties. Generally, interest will not be reimbursed. Any liability of Tarrant Advisors LLC for penalty reimbursement and any other claim related to the Services will be limited to 3 times the fees paid by Client related to the Services performed under this Agreement. 
11. We will return all source documents provided to us. We scan and keep copies of most of your supporting documents, but we are not the custodian of your records, and you cannot rely on us to maintain the supporting documents for your tax return; that is your responsibility. By accepting the returns, you acknowledge the return of all original source documents.
12. All invoices rendered for services under the terms of this agreement are <b><u>due upon receipt</u></b>. Final payment is due when you pick up or receive your completed tax returns. 
13. Additional tax consulting services including tax planning, tax authority controversy assistance, additional tax return preparation, and other tax services, as requested, will be billed based on the time incurred at our agreed upon hourly rates to range from $100-$250 based on the services performed and the tax professional involved ("agreed upon hourly rates"). 
14. We attempt to resolve any dispute fairly to all parties. If there should be any unresolved disagreement of any sort, you agree to mediation. If mediation is unsuccessful, you agree to binding arbitration under the rules of the American Arbitration Association. The limit of time for making a claim arising from our services is one year after the services are rendered.
15. If any provision herein is inoperative, the remainder of the agreement shall remain in full force and effect. This agreement is intended as the complete agreement and can only be modified in writing signed by all parties. To the extent that this Agreement is not executed, acceptance and/or filing of the completed tax returns will be deemed agreement to the terms described herein. 
{% else %}
1. We will prepare your tax returns and perform tax Services, as applicable, based only on information you provide to us. Client represents that it will provide us with information that is complete, true and accurate, disclosing all relevant facts. We will not verify the information with third parties unless you direct us too. The IRS regulations make it your responsibility to include all income and expenses.
2. Client agrees to provide all needed information required to prepare the returns and provide the Services.
3. Client agrees to respond to our requests for missing information in a timely manner.
4. Client is aware of IRS record keeping and documentation requirement and represent that you have the necessary records required. We do not audit or verify information, but we may ask for additional clarification.
5. In the event your return is selected for audit, it will be your responsibility to produce documentation, records, and other evidence to substantiate items you claimed as income and/or deductions. We can serve as your representative at our agreed upon hourly rates.
6. Client is responsible for penalties on underpayment, late filing, late payment and interest. If you are assessed a penalty because of our error and we cannot get the penalty abated, we will reimburse you or credit your account at your option for penalties. Generally, interest will not be reimbursed. Any liability of Tarrant Advisors for penalty reimbursement and any other claim related to the Services will be limited to 3 times the fees paid by Client related to the Services performed under this Agreement.
7. We will return all source documents provided to us. We scan and keep copies of most of your supporting documents, but we are not the custodian of your records, and you cannot rely on us to maintain the supporting documents for your tax return; that is your responsibility.
8. All invoices rendered for services under the terms of this agreement are due upon receipt.  Final payment is due when you pick up or receive your completed tax returns. Invoices unpaid after 30 days will be assessed a 1.5% per month late fee.
9. Additional tax consulting services including tax planning, tax authority controversy assistance, additional tax return preparation and other tax services, as requested, will be billed based on the time incurred at our agreed upon hourly rates to range from $100-$250 based on the services performed and the tax profession involved ("agreed upon hourly rates").
10. We attempt to resolve any dispute fairly to all parties. If there should be any unresolved disagreement of any sort, you agree to mediation. If mediation is unsuccessful, you agree to binding arbitration under the rules of the American Arbitration Association. The time limit for making a claim arising from our services is one year after the services are rendered.
11. If any provision herein is inoperative, the remainder of the agreement shall remain in full force and effect. This agreement is intended as the complete agreement and can only be modified in writing that is signed by all parties.

Thank you for giving Tarrant Advisors the opportunity to serve you. If you have any questions, please call me at (703) 919-2665.
{% endif %}

### Execution and Binding Acceptance

The services and terms described in this agreement are in accordance with my/our understanding and are accepted on behalf of all Taxpayers receiving services:
