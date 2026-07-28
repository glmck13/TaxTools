/**
 * 2026 Engagement Utility Front-End Orchestrator (QBO Dynamic Builder Edition)
 * Controls profile auto-auditing, dynamic row expansion/contraction, 
 * contextual filtering, real-time totals, dynamic submit actions, and read-only draft locking.
 */

let rowCounter = 0;

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
 * Appends or rehydrates a custom out-of-scope checklist item dynamically.
 */
function addCustomOutOfScopeItem(customValue = '', customKey = '', isLocked = false) {
    const input = document.getElementById('new-out-of-scope-input');
    const container = document.getElementById('out-of-scope-checklist-container');
    if (!container) return;

    const val = customValue ? customValue.trim() : (input ? input.value.trim() : '');
    if (!val) return;

    // Normalize key attribute namespace
    let nameAttr = '';
    if (customKey) {
        nameAttr = customKey.startsWith('out_of_scope_item_') ? customKey : `out_of_scope_item_${customKey}`;
    } else {
        const uniqueId = `custom_${Date.now()}_${container.querySelectorAll('.custom-out-of-scope-item').length}`;
        nameAttr = `out_of_scope_item_${uniqueId}`;
    }

    // Prevent duplicate injections by input name attribute
    if (container.querySelector(`input[name="${nameAttr}"]`)) return;

    const itemDiv = document.createElement('div');
    itemDiv.className = 'out-of-scope-checklist-item custom-out-of-scope-item';
    itemDiv.style.cssText = 'display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0;';

    const disabledAttr = isLocked ? 'disabled' : '';
    const removeBtnHtml = isLocked ? '' : '<button type="button" class="btn-remove-row" onclick="this.parentElement.remove()" title="Remove Custom Exclusion" style="margin-left: 10px;">×</button>';

    itemDiv.innerHTML = `
        <label style="font-weight: normal; display: flex; align-items: center; gap: 8px; cursor: pointer; flex-grow: 1;">
            <input type="checkbox" name="${escapeHtml(nameAttr)}" value="${escapeHtml(val)}" checked ${disabledAttr}>
            <span>${escapeHtml(val)}</span>
        </label>
        ${removeBtnHtml}
    `;

    container.appendChild(itemDiv);

    if (input && !customValue) input.value = '';
}

/**
 * Re-hydrates both standard and custom out-of-scope checklist items cleanly.
 */
function rehydrateOutOfScopeItems(oosDict, isLocked = false) {
    const container = document.getElementById('out-of-scope-checklist-container');
    if (!container) return;

    // 1. Rehydrate Standard Checkboxes
    const standardInputs = container.querySelectorAll('input[type="checkbox"]:not([name*="_custom_"])');
    standardInputs.forEach(cb => {
        if (oosDict) {
            const isKeyPresent = Object.prototype.hasOwnProperty.call(oosDict, cb.name);
            const isValPresent = Object.values(oosDict).includes(cb.value);
            cb.checked = isKeyPresent || isValPresent;
        } else {
            cb.checked = true; // Default to checked if no saved state exists
        }
        cb.disabled = isLocked;
    });

    // 2. Clear stale custom elements before rebuilding
    container.querySelectorAll('.custom-out-of-scope-item').forEach(el => el.remove());

    // 3. Rebuild Custom Items
    if (oosDict) {
        Object.keys(oosDict).forEach(key => {
            if (key.includes('_custom_') || key.includes('custom_')) {
                addCustomOutOfScopeItem(oosDict[key], key, isLocked);
            }
        });
    }
}

/**
 * Injects global hidden input fields for complete records to fulfill runtime form submission requirements.
 */
function injectHiddenMasterContext(signatureType, entityType, coSignerName, addr) {
    let container = document.getElementById('hidden-master-context');
    if (!container) {
        container = document.createElement('div');
        container.id = 'hidden-master-context';
        const table = document.getElementById('service-table');
        if (table && table.parentNode) table.parentNode.appendChild(container);
    }
    addr = addr || {};
    
    const additionalSignerEmail = (signatureType && signatureType.includes('@')) ? signatureType : '';

    container.innerHTML = `
        <input type="hidden" name="heal_profile_flag" value="false">
        <input type="hidden" name="meta_signature_type" value="${signatureType || ''}">
        <input type="hidden" name="meta_additional_signer" value="${additionalSignerEmail}">
        <input type="hidden" name="meta_entity_type" value="${entityType || ''}">
        <input type="hidden" name="meta_co_signer_name" value="${coSignerName || ''}">
        <input type="hidden" name="heal_street" value="${addr.street || ''}">
        <input type="hidden" name="heal_city" value="${addr.city || ''}">
        <input type="hidden" name="heal_state" value="${addr.state || ''}">
        <input type="hidden" name="heal_zip" value="${addr.zip || ''}">
    `;
}

/**
 * Handles the event when a staff member changes the active QBO Customer selection.
 */
function onClientChange() {
    const clientSelect = document.getElementById('client-select');
    if (!clientSelect) return;
    
    const selectedClient = clientSelect.value;
    const table = document.getElementById('service-table');
    const tbody = document.getElementById('service-tbody');
    const actionsDiv = document.getElementById('actions-container');
    const outOfScopeContainer = document.getElementById('out-of-scope-container');
    const profileContainer = document.getElementById('profile-healing-container');
    const lockBannerContainer = document.getElementById('lock-banner-container');
    const submitBtn = document.getElementById('btn-submit-main');

    // Reset workspace DOM state
    tbody.innerHTML = '';
    if (profileContainer) profileContainer.innerHTML = '';
    if (lockBannerContainer) {
        lockBannerContainer.innerHTML = '';
        lockBannerContainer.style.display = 'none';
    }
    rowCounter = 0;

    if (!selectedClient || !window.clientData || !window.clientData[selectedClient]) {
        table.style.display = 'none';
        actionsDiv.style.display = 'none';
        if (outOfScopeContainer) outOfScopeContainer.style.display = 'none';
        if (profileContainer) profileContainer.style.display = 'none';
        if (submitBtn) submitBtn.style.display = 'none';
        return;
    }

    const clientRecord = window.clientData[selectedClient];
    const metadata = clientRecord.metadata || {};
    const address = clientRecord.address || {};
    const draftData = clientRecord.saved_draft || {};
    const isLocked = Boolean(draftData.is_locked);
    const lockedMtime = draftData.locked_mtime || 'recently';

    const rawOptionText = clientSelect.options[clientSelect.selectedIndex].text;
    const rawCustomerName = rawOptionText.split(' (Customer')[0].trim();

    // Render locked banner if agreement was already dispatched
    if (isLocked && lockBannerContainer) {
        lockBannerContainer.style.display = 'block';
        lockBannerContainer.innerHTML = `
            <div class="lock-banner-card">
                <div class="lock-banner-title">🔒 Agreement Dispatched (Read-Only Mode)</div>
                <p class="lock-banner-text">
                    An engagement agreement for <strong>${escapeHtml(rawCustomerName)}</strong> was sent out on <strong>${escapeHtml(lockedMtime)}</strong>. 
                    Workspace parameters are locked to preserve the dispatched context.
                </p>
            </div>
        `;
    }

    const isAddressMissing = !address.street || !address.city || !address.state || !address.zip;
    const isConfigMissing = !metadata.entity_type;
    const isProfileIncomplete = isAddressMissing || isConfigMissing;

    if (profileContainer) {
        profileContainer.style.display = 'block';
        if (isProfileIncomplete) {
            renderEditableProfilePanel(profileContainer, address, metadata, rawCustomerName, clientRecord.email);
        } else {
            renderReadOnlyProfilePanel(profileContainer, address, metadata, rawCustomerName, clientRecord.email);
            injectHiddenMasterContext(metadata.signature_type, metadata.entity_type, metadata.co_signer_name, address);
        }
    }

    if (submitBtn) {
        submitBtn.innerText = isLocked ? 'View Sent Agreement (Read-Only)' : 'Render PDF Preview';
        submitBtn.style.display = 'block';
    }

    table.style.display = 'table';
    actionsDiv.style.display = isLocked ? 'none' : 'flex';
    if (outOfScopeContainer) outOfScopeContainer.style.display = 'block';

    // Priority hierarchy for state recovery: Preserved Form > Disk Draft
    const hasPreservedHeal = window.preservedHealData && Object.keys(window.preservedHealData).length > 0;
    const healData = hasPreservedHeal ? window.preservedHealData : draftData;

    const dateSelect = document.getElementById('estimate-date-option');
    if (dateSelect) {
        if (healData.estimate_date_option) dateSelect.value = healData.estimate_date_option;
        dateSelect.disabled = isLocked;
    }

    // Populate preserved field states
    ['friendly_name', 'heal_street', 'heal_city', 'heal_state', 'heal_zip', 'meta_co_signer_name'].forEach(fieldName => {
        const input = document.querySelector(`input[name="${fieldName}"]`);
        if (input && healData[fieldName]) input.value = healData[fieldName];
    });

    const hEntity = document.querySelector('select[name="meta_entity_type"]');
    if (hEntity && healData.meta_entity_type) hEntity.value = healData.meta_entity_type;

    // SURGICAL FIX #1: Map meta_additional_signer ONLY if present, never overwrite with meta_signature_type
    const hSig = document.querySelector('input[name="meta_additional_signer"]');
    if (hSig) {
        if (healData.meta_additional_signer) {
            hSig.value = healData.meta_additional_signer;
        } else {
            hSig.value = '';
        }
    }

    if (isLocked && profileContainer) {
        profileContainer.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
    }

    // Rehydrate Table Rows
    if (window.reconstructedRows && window.reconstructedRows.length > 0) {
        window.reconstructedRows.forEach(row => addServiceRow(row, isLocked));
    } else if (draftData.rows && draftData.rows.length > 0) {
        draftData.rows.forEach(row => addServiceRow(row, isLocked));
    } else {
        addServiceRow(null, isLocked);
    }

    // Rehydrate Out-Of-Scope Checklist
    const oosDict = healData.out_of_scope_items || draftData.out_of_scope_items;
    rehydrateOutOfScopeItems(oosDict, isLocked);

    // Disable custom item inputs if locked
    const customOosInput = document.getElementById('new-out-of-scope-input');
    const customOosBtn = document.querySelector('.add-out-of-scope-row button');
    if (customOosInput) customOosInput.disabled = isLocked;
    if (customOosBtn) customOosBtn.disabled = isLocked;
}

/**
 * Renders the editable data correction form layout.
 */
function renderEditableProfilePanel(container, addr, meta, defaultFriendlyName, clientEmail) {
    // SURGICAL FIX #2: Extract coSignerEmailVal only if signature_type contains an '@'
    const coSignerEmailVal = meta.signature_type && meta.signature_type.includes('@') ? meta.signature_type : '';
    const coSignerNameVal = meta.co_signer_name || '';

    container.innerHTML = `
        <div class="profile-card profile-card-incomplete">
            <div class="profile-card-title">⚠️ Missing Required Account Settings</div>
            <p style="margin: 0 0 15px 0; font-size: 13px; color: #666;">
                This customer profile is missing vital parameters in QuickBooks Online. Please enter the details below. 
                Submitting this form will permanently heal the customer record before establishing the Estimate.
            </p>

            <div style="margin-bottom: 15px; padding: 10px; background: #fffcf5; border-left: 3px solid #b76200; font-size: 13px;">
                <strong>Adobe Sign Target Destination:</strong> 
                <span style="font-family: monospace; color: #222;">${clientEmail ? clientEmail : '<span style="color: #e53e3e; font-weight: bold;">⚠️ MISSING EMAIL IN QBO!</span>'}</span>
            </div>

            <input type="hidden" name="heal_profile_flag" value="true">
            <div class="profile-grid-layout profile-editable-grid">
                <div class="form-field-group">
                    <label class="field-label">Friendly Name</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(defaultFriendlyName)}" required placeholder="e.g., Susan Smith">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Street Address</label>
                    <input type="text" name="heal_street" value="${escapeHtml(addr.street)}" required placeholder="e.g., 123 Main St">
                </div>
                <div class="form-field-group">
                    <label class="field-label">City</label>
                    <input type="text" name="heal_city" value="${escapeHtml(addr.city)}" required placeholder="e.g., Fort Worth">
                </div>
                <div class="form-field-group">
                    <label class="field-label">State</label>
                    <input type="text" name="heal_state" value="${escapeHtml(addr.state)}" required placeholder="TX" maxlength="2">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Zip Code</label>
                    <input type="text" name="heal_zip" value="${escapeHtml(addr.zip)}" required placeholder="76102">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Account Classification</label>
                    <select name="meta_entity_type" id="heal_entity_type" onchange="onProfileEntityChange()" required>
                        <option value="">-- Choose Classification --</option>
                        <option value="individual" ${meta.entity_type === 'individual' ? 'selected' : ''}>Individual (Form 1040)</option>
                        <option value="s_corp" ${meta.entity_type === 's_corp' ? 'selected' : ''}>S-Corporation (Form 1120S)</option>
                        <option value="partnership" ${meta.entity_type === 'partnership' ? 'selected' : ''}>Partnership (Form 1065)</option>
                        <option value="c_corp" ${meta.entity_type === 'c_corp' ? 'selected' : ''}>C-Corporation (Form 1120)</option>
                        <option value="non_profit" ${meta.entity_type === 'non_profit' ? 'selected' : ''}>Tax-Exempt Org (Form 990)</option>
                        <option value="trust" ${meta.entity_type === 'trust' ? 'selected' : ''}>Trust / Estate (Form 1041)</option>
                    </select>
                </div>
                <div class="form-field-group">
                    <label class="field-label">Additional Signer Full Name</label>
                    <input type="text" name="meta_co_signer_name" value="${escapeHtml(coSignerNameVal)}" placeholder="e.g., Jane Doe">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Additional Signer Email</label>
                    <input type="email" name="meta_additional_signer" value="${escapeHtml(coSignerEmailVal)}" placeholder="spouse@example.com">
                </div>
            </div>
        </div>
    `;
}

/**
 * Renders an immutable read-only view block when customer parameters are satisfied.
 */
function renderReadOnlyProfilePanel(container, addr, meta, defaultFriendlyName, clientEmail) {
    const formattedAddress = `${addr.street || ''}, ${addr.city || ''}, ${addr.state || ''} ${addr.zip || ''}`;
    const displayMap = {
        'individual': 'Individual',
        's_corp': 'S-Corporation',
        'partnership': 'Partnership',
        'c_corp': 'C-Corporation',
        'non_profit': 'Tax-Exempt Org',
        'trust': 'Trust / Estate'
    };
    const displayClassification = displayMap[meta.entity_type] || meta.entity_type || 'Individual';
    const isOrg = ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust'].includes(meta.entity_type);
    const coSignerDisplayName = meta.co_signer_name ? `${meta.co_signer_name} (${meta.signature_type})` : meta.signature_type;

    container.innerHTML = `
        <div class="profile-card profile-card-complete">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div class="profile-card-title" style="color: #107c41; margin-bottom: 0;">✓ Customer Profile Verified</div>
                <button type="button" class="btn-add-row btn-edit-profile" onclick="toggleProfileEditMode()" style="font-size: 12px; padding: 4px 10px;">✏️ Edit Profile Parameters</button>
            </div>
            <div style="margin-bottom: 15px; display: grid; grid-template-columns: 1fr; gap: 10px;">
                <div class="form-field-group">
                    <label class="field-label" style="font-weight: 600; font-size: 13px; margin-bottom: 4px;">Friendly Name (Override text if needed)</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(defaultFriendlyName)}" style="width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px;" required>
                </div>
            </div>
            <div class="profile-grid-layout markdown-verified-grid">
                <div><strong>Billing Address:</strong><br><span style="color:#555;">${escapeHtml(formattedAddress)}</span></div>
                <div><strong>Email:</strong><br><span style="color:#555; font-family: monospace; font-size: 12px;">${clientEmail ? escapeHtml(clientEmail) : '[None Sourced]'}</span></div>
                <div><strong>Classification:</strong><br><span class="badge ${isOrg ? 'badge-organization' : 'badge-individual'}">${escapeHtml(displayClassification)}</span></div>
                <!-- SURGICAL FIX #3: Verify additional signer badge via '@' symbol presence -->
                <div><strong>Signature Grid:</strong><br><span style="color:#555;">${meta.signature_type && meta.signature_type.includes('@') ? 'Additional Signer: ' + escapeHtml(coSignerDisplayName) : 'Single Signer'}</span></div>
            </div>
            <p style="margin: 12px 0 0 0; font-size: 11px; color: #888; font-style: italic;">
                To alter verified master address or classification properties, modify the customer card directly within the QuickBooks Online dashboard interface or click Edit Profile Parameters above.
            </p>
        </div>
    `;
}

/**
 * Unlocks the profile parameters form into editable fields.
 */
function toggleProfileEditMode() {
    const selectEl = document.getElementById('client-select');
    const selectedClient = selectEl ? selectEl.value : '';
    const container = document.getElementById('profile-healing-container');
    if (!selectedClient || !container || !window.clientData[selectedClient]) return;

    const record = window.clientData[selectedClient];
    const friendlyInput = document.querySelector('input[name="friendly_name"]');
    const defaultFriendlyName = friendlyInput ? friendlyInput.value : selectEl.options[selectEl.selectedIndex].text.split(' (Customer')[0].trim();

    renderEditableProfilePanel(container, record.address || {}, record.metadata || {}, defaultFriendlyName, record.email);
    
    const healFlagInput = container.querySelector('input[name="heal_profile_flag"]');
    if (healFlagInput) healFlagInput.value = "true";
}

/**
 * Updates dropdown options if classification choice changes.
 */
function onProfileEntityChange() {
    const clientSelect = document.getElementById('client-select');
    const selectedClient = clientSelect ? clientSelect.value : '';
    if (!selectedClient || !window.clientData || !window.clientData[selectedClient]) return;

    const exposedServices = window.clientData[selectedClient].exposed_services || [];
    const healEntitySelect = document.getElementById('heal_entity_type');
    const currentRawEntity = healEntitySelect ? healEntitySelect.value.toLowerCase() : '';

    if (currentRawEntity) {
        window.clientData[selectedClient].metadata = window.clientData[selectedClient].metadata || {};
        window.clientData[selectedClient].metadata.entity_type = currentRawEntity;
    }

    const currentContextType = ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust'].includes(currentRawEntity) ? 'organization' : 'individual';

    document.querySelectorAll('input[name="selected_rows"]').forEach(r => {
        const id = r.value;
        const selectEl = document.querySelector(`select[name="row_item_id_${id}"]`);
        if (selectEl) {
            const currentValue = selectEl.value;
            let optionsHtml = `<option value="">-- Select an Offering --</option>`;
            exposedServices.forEach(svc => {
                const svcType = svc.type ? svc.type.toLowerCase() : '';
                if (!currentRawEntity || svcType === 'both' || svcType === currentContextType) {
                    optionsHtml += `<option value="${svc.id}" data-type="${svc.type}">${escapeHtml(svc.name)}</option>`;
                }
            });
            selectEl.innerHTML = optionsHtml;
            selectEl.value = currentValue;
        }
        onRowItemChange(id, true);
    });
}

/**
 * Appends a service line row to the builder workspace layout.
 */
function addServiceRow(rowData = null, isLocked = false) {
    const tbody = document.getElementById('service-tbody');
    const clientSelect = document.getElementById('client-select');
    const selectedClient = clientSelect ? clientSelect.value : '';

    if (!selectedClient || !window.clientData || !window.clientData[selectedClient]) return;

    const exposedServices = window.clientData[selectedClient].exposed_services || [];
    let currentRawEntity = '';
    const healEntitySelect = document.getElementById('heal_entity_type');
    
    if (healEntitySelect && healEntitySelect.value) {
        currentRawEntity = healEntitySelect.value.toLowerCase();
    } else if (window.clientData[selectedClient].metadata && window.clientData[selectedClient].metadata.entity_type) {
        currentRawEntity = window.clientData[selectedClient].metadata.entity_type.toLowerCase();
    }

    const currentContextType = ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust'].includes(currentRawEntity) ? 'organization' : 'individual';

    rowCounter++;
    const currentId = rowCounter;
    const tr = document.createElement('tr');
    tr.id = `row_container_${currentId}`;

    let targetService = rowData ? rowData.service : '';
    try { if (targetService) targetService = decodeURIComponent(targetService); } catch(e) {}

    const feeValue = rowData ? rowData.fee : '0.00';
    const notesValue = rowData ? rowData.notes : '';
    const bpValue = rowData ? rowData.bp : 'individual';
    const targetItemId = rowData ? String(rowData.item_id) : '';

    let optionsHtml = `<option value="">-- Select an Offering --</option>`;
    exposedServices.forEach(svc => {
        const svcType = svc.type ? svc.type.toLowerCase() : '';
        const svcNameNorm = svc.name ? svc.name.trim().toLowerCase() : '';
        const targetServiceNorm = targetService ? targetService.trim().toLowerCase() : '';
        const svcIdStr = String(svc.id);

        const isMatch = rowData && (
            (targetServiceNorm && svcNameNorm === targetServiceNorm) ||
            (targetItemId && svcIdStr === targetItemId)
        );

        const isAllowedByEntity = !currentRawEntity || svcType === 'both' || svcType === currentContextType;

        if (isAllowedByEntity || isMatch) {
            const isSelected = isMatch ? 'selected' : '';
            optionsHtml += `<option value="${svc.id}" data-type="${svc.type}" ${isSelected}>${escapeHtml(svc.name)}</option>`;
        }
    });

    const disabledAttr = isLocked ? 'disabled' : '';

    tr.innerHTML = `
        <td style="text-align: center; width: 40px; padding-top: 16px;">
            ${isLocked ? '' : `<button type="button" class="btn-remove-row" onclick="removeServiceRow(${currentId})" title="Remove Line">×</button>`}
            <input type="hidden" name="selected_rows" value="${currentId}">
        </td>
        <td>
            <select name="row_item_id_${currentId}" onchange="onRowItemChange(${currentId})" required style="width: 98%; padding: 8px;" ${disabledAttr}>
                ${optionsHtml}
            </select>
            <div id="badge_container_${currentId}" style="margin-top: 5px; margin-left: 2px;"></div>
            <input type="hidden" id="row_bp_${currentId}" name="row_bp_${currentId}" value="${escapeHtml(bpValue)}">
            <input type="hidden" id="row_service_${currentId}" name="row_service_${currentId}" value="${encodeURIComponent(targetService)}">
        </td>
        <td style="white-space: nowrap; width: 135px;">
            <span style="position: relative; font-family: monospace; font-size: 15px; top: 4px;">
                $ <input type="number" name="row_fee_${currentId}" id="row_fee_${currentId}" step="0.01" min="-99999.99" value="${escapeHtml(feeValue)}" oninput="calculateGridTotals()" style="width: 90px; padding: 6px;" required ${disabledAttr}>
            </span>
        </td>
        <td class="notes-cell">
            <textarea name="row_notes_${currentId}" placeholder="Enter custom line parameters or scope exclusions..." style="width: 98%; height: 46px; font-family: inherit; font-size: 13px; padding: 6px; box-sizing: border-box;" ${disabledAttr}>${escapeHtml(notesValue)}</textarea>
        </td>
    `;

    tbody.appendChild(tr);

    // Always trigger onRowItemChange to keep hidden input fields 
    // (row_service_X and row_bp_X) in perfect sync with the DOM select element
    onRowItemChange(currentId, Boolean(rowData));
}

/**
 * Removes a service line row and updates totals.
 */
function removeServiceRow(id) {
    const tr = document.getElementById(`row_container_${id}`);
    if (tr) tr.remove();
    calculateGridTotals();
}

/**
 * Event listener triggered when item select choice changes inside a line.
 */
function onRowItemChange(id, bypassDefaultNotes = false) {
    const selectEl = document.querySelector(`select[name="row_item_id_${id}"]`);
    const badgeContainer = document.getElementById(`badge_container_${id}`);
    const bpInput = document.getElementById(`row_bp_${id}`);
    const svcNameInput = document.getElementById(`row_service_${id}`);
    const notesTextarea = document.querySelector(`textarea[name="row_notes_${id}"]`);

    if (!selectEl) return;

    const selectedOption = selectEl.options[selectEl.selectedIndex];
    
    if (!selectedOption || selectEl.value === "") {
        if (badgeContainer) badgeContainer.innerHTML = '';
        if (bpInput) bpInput.value = 'individual';
        if (svcNameInput) svcNameInput.value = '';
        if (notesTextarea) notesTextarea.value = '';
        calculateGridTotals();
        return;
    }

    const rawType = selectedOption.getAttribute('data-type') || 'individual';
    const itemName = selectedOption.text;
    if (svcNameInput) svcNameInput.value = encodeURIComponent(itemName);

    let resolvedType = rawType;
    const clientSelect = document.getElementById('client-select');
    const selectedClient = clientSelect ? clientSelect.value : '';

    if (['both', 'individual', 'organization'].includes(rawType.toLowerCase())) {
        const healEntitySelect = document.getElementById('heal_entity_type');
        let currentRawEntity = 'individual';
        if (healEntitySelect && healEntitySelect.value) {
            currentRawEntity = healEntitySelect.value.toLowerCase();
        } else if (selectedClient && window.clientData && window.clientData[selectedClient]) {
            const meta = window.clientData[selectedClient].metadata || {};
            currentRawEntity = (meta.entity_type || 'individual').toLowerCase();
        }
        resolvedType = ['s_corp', 'partnership', 'c_corp', 'non_profit', 'trust'].includes(currentRawEntity) ? 'organization' : 'individual';
    }

    if (bpInput) bpInput.value = resolvedType;

    if (badgeContainer) {
        const isOrganization = (resolvedType.toLowerCase() === 'organization');
        badgeContainer.innerHTML = `<span class="badge ${isOrganization ? 'badge-organization' : 'badge-individual'}">${escapeHtml(resolvedType)}</span>`;
    }

    if (!bypassDefaultNotes && notesTextarea && selectedClient && window.clientData && window.clientData[selectedClient]) {
        const exposedServices = window.clientData[selectedClient].exposed_services || [];
        const serviceMatch = exposedServices.find(svc => svc.name === itemName);
        notesTextarea.value = serviceMatch ? (serviceMatch.notes || '') : '';
    }

    calculateGridTotals();
}

/**
 * Compiles live financial totals for display in table footer.
 */
function calculateGridTotals() {
    let totalBaseFee = 0.0;
    let discountAmount = 0.0;

    document.querySelectorAll('input[name="selected_rows"]').forEach(input => {
        const id = input.value;
        const feeInput = document.getElementById(`row_fee_${id}`);
        const selectEl = document.querySelector(`select[name="row_item_id_${id}"]`);
        
        if (feeInput && selectEl) {
            const feeValue = parseFloat(feeInput.value) || 0.0;
            const selectedOption = selectEl.options[selectEl.selectedIndex];
            const itemName = selectedOption ? selectedOption.text.toLowerCase() : '';

            if (itemName.includes('deposit') || itemName.includes('retainer')) return;

            if (itemName.includes('discount') || itemName.includes('referral')) {
                discountAmount += Math.abs(feeValue);
            } else {
                totalBaseFee += feeValue;
            }
        }
    });

    const totalNet = totalBaseFee - discountAmount;

    const discountNode = document.getElementById('ui-total-discount');
    const balanceNode = document.getElementById('ui-total-balance');

    if (discountNode) discountNode.innerText = discountAmount > 0 ? `-$${discountAmount.toFixed(2)}` : `$0.00`;
    if (balanceNode) balanceNode.innerText = `$${totalNet.toFixed(2)}`;
}

// Global Form Submit Safeguard
document.addEventListener('DOMContentLoaded', () => {
    const form = document.querySelector('form');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        const table = document.getElementById('service-table');
        if (table) {
            table.querySelectorAll('input, select, textarea').forEach(el => {
                el.disabled = false;
            });
        }

        const oosContainer = document.getElementById('out-of-scope-checklist-container');
        if (oosContainer) {
            oosContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.disabled = false;
            });
        }

        const action = e.submitter ? e.submitter.value : '';
        if (action === 'revert_to_workspace') return true;

        const clientSelect = document.getElementById('client-select');
        if (!clientSelect || !clientSelect.value) return true;

        const clientRecord = window.clientData[clientSelect.value];
        if (clientRecord && clientRecord.saved_draft && clientRecord.saved_draft.is_locked) return true;

        const addSignerInput = document.querySelector('input[name="meta_additional_signer"]');
        const coSignerNameInput = document.querySelector('input[name="meta_co_signer_name"]');

        const hasEmail = addSignerInput && addSignerInput.value.trim() !== "";
        const hasName = coSignerNameInput && coSignerNameInput.value.trim() !== "";

        if (hasEmail || hasName) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (hasEmail && !emailRegex.test(addSignerInput.value.trim())) {
                alert("Please enter a valid email address for the Additional Signer field.");
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
