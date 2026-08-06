/**
 * Tarrant Advisors - Section 7216 Consent Portal Front-End Orchestrator
 * Controls customer selection changes, dynamic local address fallback rendering,
 * friendly name & legal name population, and form submission validation.
 */

/**
 * Utility helper to sanitize dynamic text strings before DOM insertion.
 */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/**
 * Utility helper to decode HTML entities (e.g., &amp; -> &)
 */
function unescapeHtml(str) {
    if (!str) return '';
    const txt = document.createElement('textarea');
    txt.innerHTML = str;
    return txt.value;
}

/**
 * Handles the event when a staff member selects a different QBO Customer.
 */
function onClientChange() {
    const clientSelect = document.getElementById('client-select');
    if (!clientSelect) return;

    const selectedClient = clientSelect.value;
    const profileContainer = document.getElementById('profile-container');
    const submitBtn = document.getElementById('btn-submit-main');

    // Reset workspace DOM state
    if (profileContainer) profileContainer.innerHTML = '';

    if (!selectedClient || !window.clientData || !window.clientData[selectedClient]) {
        if (profileContainer) profileContainer.style.display = 'none';
        if (submitBtn) submitBtn.style.display = 'none';
        return;
    }

    const clientRecord = window.clientData[selectedClient];
    const address = clientRecord.address || {};
    
    // Support both <input list="..."> and legacy <select> elements for name extraction
    const rawText = clientSelect.value || (clientSelect.options && clientSelect.selectedIndex >= 0 ? clientSelect.options[clientSelect.selectedIndex].text : '');
    const rawOptionText = unescapeHtml(rawText);
    const rawCustomerName = rawOptionText.split(/\s*\(Customer/)[0].trim();

    const healData = window.preservedHealData || {};
    const defaultFriendlyName = healData.friendly_name || rawCustomerName;
    const defaultLegalName = healData.local_legal_name || rawCustomerName;

    const isAddressMissing = !address.street || !address.city || !address.state || !address.zip;

    if (profileContainer) {
        profileContainer.style.display = 'block';
        if (isAddressMissing) {
            renderFallbackAddressPanel(profileContainer, address, defaultFriendlyName, defaultLegalName, clientRecord.email);
        } else {
            renderVerifiedProfilePanel(profileContainer, address, defaultFriendlyName, defaultLegalName, clientRecord.email);
        }
    }

    if (submitBtn) {
        submitBtn.style.display = 'block';
    }

    // Hydrate preserved form values if available (e.g. on workspace revert or reload)
    if (healData.friendly_name) {
        const friendlyInput = document.querySelector('input[name="friendly_name"]');
        if (friendlyInput) friendlyInput.value = healData.friendly_name;
    }
    if (healData.local_legal_name) {
        const legalInput = document.querySelector('input[name="local_legal_name"]');
        if (legalInput) legalInput.value = healData.local_legal_name;
    }
    if (healData.tax_years_covered) {
        const taxYearsSelect = document.getElementById('tax-years-covered');
        if (taxYearsSelect) taxYearsSelect.value = healData.tax_years_covered;
    }
    if (healData.local_street) {
        const streetInput = document.querySelector('input[name="local_street"]');
        if (streetInput) streetInput.value = healData.local_street;
    }
    if (healData.local_city) {
        const cityInput = document.querySelector('input[name="local_city"]');
        if (cityInput) cityInput.value = healData.local_city;
    }
    if (healData.local_state) {
        const stateInput = document.querySelector('input[name="local_state"]');
        if (stateInput) stateInput.value = healData.local_state;
    }
    if (healData.local_zip) {
        const zipInput = document.querySelector('input[name="local_zip"]');
        if (zipInput) zipInput.value = healData.local_zip;
    }
    if (healData.meta_co_signer_name) {
        const coSignerNameInput = document.querySelector('input[name="meta_co_signer_name"]');
        if (coSignerNameInput) coSignerNameInput.value = healData.meta_co_signer_name;
    }
    if (healData.meta_additional_signer) {
        const coSignerEmailInput = document.querySelector('input[name="meta_additional_signer"]');
        if (coSignerEmailInput) coSignerEmailInput.value = healData.meta_additional_signer;
    }

    // Clear preserved memory after initial hydration pass to prevent leaks across client switches
    window.preservedHealData = {};
}

/**
 * Renders an address fallback panel when QBO address is incomplete.
 * Note: These fields are strictly used for document generation and are NOT written back to QBO.
 */
function renderFallbackAddressPanel(container, addr, defaultFriendlyName, defaultLegalName, clientEmail) {
    // Explicitly fallback to empty string to ensure no leak from prior client selection
    const street = addr.street ? addr.street : '';
    const city = addr.city ? addr.city : '';
    const state = addr.state ? addr.state : '';
    const zip = addr.zip ? addr.zip : '';

    container.innerHTML = `
        <div class="profile-card profile-card-fallback">
            <div class="profile-card-title" style="color: #b76200;">⚠️ Incomplete Billing Address in QBO</div>
            <p style="margin: 0 0 15px 0; font-size: 13px; color: #666;">
                QuickBooks Online does not have a complete billing address for this customer. Please enter the address below for the consent letter. 
                <em>(Note: This address will only be used for this consent document and will NOT be written back to QuickBooks Online.)</em>
            </p>

            <div style="margin-bottom: 15px; padding: 10px; background: #fffcf5; border-left: 3px solid #b76200; font-size: 13px;">
                <strong>Target Email:</strong> 
                <span style="font-family: monospace; color: #222;">${clientEmail ? escapeHtml(clientEmail) : '<span style="color: #e53e3e; font-weight: bold;">⚠️ MISSING EMAIL IN QBO!</span>'}</span>
            </div>

            <div class="profile-grid-layout">
                <div class="form-field-group">
                    <label class="field-label">Friendly Name</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(unescapeHtml(defaultFriendlyName))}" required placeholder="e.g., Jack Fleisher">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Legal Name (For Documents)</label>
                    <input type="text" name="local_legal_name" value="${escapeHtml(unescapeHtml(defaultLegalName))}" required placeholder="e.g., Jack Fleisher LLC">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Street Address (Local Only)</label>
                    <input type="text" name="local_street" value="${escapeHtml(street)}" required placeholder="e.g., 7520 Woodside Lane">
                </div>
                <div class="form-field-group">
                    <label class="field-label">City (Local Only)</label>
                    <input type="text" name="local_city" value="${escapeHtml(city)}" required placeholder="e.g., Lorton">
                </div>
                <div class="form-field-group">
                    <label class="field-label">State (Local Only)</label>
                    <input type="text" name="local_state" value="${escapeHtml(state)}" required placeholder="VA" maxlength="2">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Zip Code (Local Only)</label>
                    <input type="text" name="local_zip" value="${escapeHtml(zip)}" required placeholder="22079">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Full Name (Optional)</label>
                    <input type="text" name="meta_co_signer_name" value="" placeholder="e.g., Jane Fleisher">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Email (Optional)</label>
                    <input type="email" name="meta_additional_signer" value="" placeholder="spouse@example.com">
                </div>
            </div>
        </div>
    `;
}

/**
 * Renders verified profile panel when complete customer parameters exist in QBO.
 */
function renderVerifiedProfilePanel(container, addr, defaultFriendlyName, defaultLegalName, clientEmail) {
    const formattedAddress = `${addr.street || ''}, ${addr.city || ''}, ${addr.state || ''} ${addr.zip || ''}`;

    container.innerHTML = `
        <div class="profile-card profile-card-complete">
            <div class="profile-card-title" style="color: #107c41;">✓ Customer Address Verified</div>
            
            <!-- Hidden inputs to pass verified address data -->
            <input type="hidden" name="local_street" value="${escapeHtml(addr.street || '')}">
            <input type="hidden" name="local_city" value="${escapeHtml(addr.city || '')}">
            <input type="hidden" name="local_state" value="${escapeHtml(addr.state || '')}">
            <input type="hidden" name="local_zip" value="${escapeHtml(addr.zip || '')}">

            <div style="margin-bottom: 15px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div class="form-field-group">
                    <label class="field-label" style="font-weight: 600; font-size: 13px;">Friendly Name (Override if needed)</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(unescapeHtml(defaultFriendlyName))}" required>
                </div>
                <div class="form-field-group">
                    <label class="field-label" style="font-weight: 600; font-size: 13px;">Legal Name (Document Override)</label>
                    <input type="text" name="local_legal_name" value="${escapeHtml(unescapeHtml(defaultLegalName))}" required>
                </div>
            </div>

            <div class="profile-grid-layout">
                <div class="verify-text"><strong>Billing Address:</strong><br><span style="color:#555;">${escapeHtml(formattedAddress)}</span></div>
                <div class="verify-text"><strong>Target Email:</strong><br><span style="color:#555; font-family: monospace;">${clientEmail ? escapeHtml(clientEmail) : '[None Sourced]'}</span></div>
            </div>

            <div style="margin-top: 15px; padding-top: 12px; border-top: 1px dashed #c6f6d5;" class="profile-grid-layout">
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Full Name (Optional)</label>
                    <input type="text" name="meta_co_signer_name" value="" placeholder="e.g., Jane Fleisher">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Email (Optional)</label>
                    <input type="email" name="meta_additional_signer" value="" placeholder="spouse@example.com">
                </div>
            </div>
        </div>
    `;
}

// Global Form Submit Safeguard
document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        const action = e.submitter ? e.submitter.value : '';
        if (action === 'revert_to_workspace') return true;

        const clientSelect = document.getElementById('client-select');
        if (!clientSelect || !clientSelect.value) return true;

        const addSignerInput = document.querySelector('input[name="meta_additional_signer"]');
        const coSignerNameInput = document.querySelector('input[name="meta_co_signer_name"]');

        const hasEmail = addSignerInput && addSignerInput.value.trim() !== "";
        const hasName = coSignerNameInput && coSignerNameInput.value.trim() !== "";

        if (hasEmail || hasName) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (hasEmail && !emailRegex.test(addSignerInput.value.trim())) {
                alert("Please enter a valid email address for the Co-Signer Email field.");
                e.preventDefault();
                return false;
            }
            if (hasEmail && !hasName) {
                alert("Please enter the Co-Signer's Full Name along with their email address.");
                e.preventDefault();
                return false;
            }
            if (hasName && !hasEmail) {
                alert("Please enter the Co-Signer's Email Address along with their full name.");
                e.preventDefault();
                return false;
            }
        }
    });
});