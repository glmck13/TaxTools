/**
 * 2026 Engagement Utility Front-End Orchestrator (QBO Dynamic Builder Edition)
 * Controls profile auto-auditing, dynamic row expansion/contraction, 
 * contextual filtering, real-time totals, dynamic submit actions, batch processing,
 * single & batch scope cloning, and read-only draft locking.
 */

let rowCounter = 0;

// Global Configuration
const BATCH_THROTTLE_DELAY_MS = 500; // Pause between batch requests (in milliseconds)

/**
 * Utility helper to pause execution for a given duration in milliseconds.
 */
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Utility helper to sanitize dynamic text strings before DOM insertion.
 */
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
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
 * Toggles visibility of the Single Client Inline Copy Toolbar.
 */
function toggleInlineCopyBar(show) {
    const toolbar = document.getElementById('inline-copy-toolbar');
    if (toolbar) {
        toolbar.style.display = show ? 'block' : 'none';
        if (!show) {
            const input = document.getElementById('clone-source-input');
            if (input) input.value = '';
        }
    }
}

/**
 * Toggles visibility of the Batch Bulk Copy Toolbar in the Batch Dashboard.
 */
function toggleBatchBulkCopyToolbar(show) {
    const toolbar = document.getElementById('batch-bulk-copy-toolbar');
    if (toolbar) {
        toolbar.style.display = show ? 'block' : 'none';
        if (!show) {
            const input = document.getElementById('batch-bulk-source-input');
            if (input) input.value = '';
        }
    }
}

/**
 * Single Workspace: Clones service lines, prices, notes, and out-of-scope selections 
 * from a chosen source client into the current active workspace.
 */
function applyClonedScopeFromSource() {
    const sourceInput = document.getElementById('clone-source-input');
    const targetSelect = document.getElementById('client-select');

    if (!sourceInput || !targetSelect || !sourceInput.value) {
        alert("Please select a valid source client to copy scope from.");
        return;
    }

    const sourceKey = unescapeHtml(sourceInput.value.trim());
    const targetKey = targetSelect.value;

    if (!window.clientData || !window.clientData[sourceKey]) {
        alert("Unable to locate draft records for the chosen source client.");
        return;
    }

    const sourceRecord = window.clientData[sourceKey];
    const sourceDraft = sourceRecord.saved_draft;

    if (!sourceDraft || !sourceDraft.rows || sourceDraft.rows.length === 0) {
        alert("Selected source client has no saved service offerings to copy.");
        return;
    }

    // Safeguard confirmation if target workspace already contains lines
    const tbody = document.getElementById('service-tbody');
    const existingRows = tbody ? tbody.querySelectorAll('tr') : [];
    if (existingRows.length > 0) {
        if (!confirm("Applying scope from source client will replace current line items and out-of-scope selections in this workspace. Continue?")) {
            return;
        }
    }

    // 1. Clear current service table rows
    if (tbody) tbody.innerHTML = '';
    rowCounter = 0;

    // 2. Clone service line rows
    sourceDraft.rows.forEach(row => {
        addServiceRow(row, false);
    });

    // 3. Clone out-of-scope items
    if (sourceDraft.out_of_scope_items) {
        rehydrateOutOfScopeItems(sourceDraft.out_of_scope_items, false);
    }

    // 4. Clone estimate date option if present
    if (sourceDraft.estimate_date_option) {
        const estDateSelect = document.getElementById('estimate-date-option');
        if (estDateSelect) estDateSelect.value = sourceDraft.estimate_date_option;
    }

    // Recalculate workspace financial totals
    calculateGridTotals();

    // Hide copy bar and clear input
    toggleInlineCopyBar(false);
}

/**
 * Batch Dashboard: Bulk applies a source client's scope setup across all checked 
 * clients in the Batch Grid and issues background AJAX draft saves.
 */
async function applyBatchBulkClonedScope() {
    const sourceInput = document.getElementById('batch-bulk-source-input');
    const checkedCheckboxes = document.querySelectorAll('.batch-checkbox:checked');

    if (!sourceInput || !sourceInput.value) {
        alert("Please select a valid source client or draft package.");
        return;
    }

    if (checkedCheckboxes.length === 0) {
        alert("Please select at least one batch client to receive the cloned scope.");
        return;
    }

    const sourceKey = unescapeHtml(sourceInput.value.trim());
    if (!window.clientData || !window.clientData[sourceKey]) {
        alert("Unable to locate draft records for the chosen source client.");
        return;
    }

    const sourceDraft = window.clientData[sourceKey].saved_draft;
    if (!sourceDraft || !sourceDraft.rows || sourceDraft.rows.length === 0) {
        alert("Selected source client has no saved service offerings to copy.");
        return;
    }

    if (!confirm(`Apply cloned scope (${sourceDraft.rows.length} item(s)) to ${checkedCheckboxes.length} checked batch client(s)?`)) {
        return;
    }

    toggleBatchBulkCopyToolbar(false);

    // Show Progress Overlay during bulk update
    const progressOverlay = document.getElementById('batch-progress-overlay');
    const progressBar = document.getElementById('batch-progress-fill');
    const terminalLog = document.getElementById('batch-terminal-log');
    const doneBtn = document.getElementById('btn-close-progress');

    progressOverlay.style.display = 'flex';
    doneBtn.style.display = 'none';
    terminalLog.innerHTML = `Cloning scope from [${sourceKey.split(' (Customer')[0]}] to ${checkedCheckboxes.length} client(s)...\n`;

    let completed = 0;

    for (const cb of checkedCheckboxes) {
        const qboId = cb.getAttribute('data-qbo-id');
        const clientKey = Object.keys(window.clientData).find(k => window.clientData[k].id === qboId);
        
        if (!clientKey) continue;

        const targetClient = window.clientData[clientKey];
        const existingDraft = targetClient.saved_draft || {};

        terminalLog.innerHTML += `\n[${completed + 1}/${checkedCheckboxes.length}] Applying scope to ${clientKey.split(' (Customer')[0]}... `;

        const urlParams = new URLSearchParams();
        urlParams.append('action', 'save_draft_only');
        urlParams.append('ajax', 'true');
        urlParams.append('client_name', clientKey);

        urlParams.append('estimate_date_option', sourceDraft.estimate_date_option || existingDraft.estimate_date_option || 'next_year');
        urlParams.append('friendly_name', existingDraft.friendly_name || clientKey.split(' (Customer')[0]);
        urlParams.append('heal_legal_name', existingDraft.heal_legal_name || clientKey.split(' (Customer')[0]);
        urlParams.append('meta_entity_type', existingDraft.meta_entity_type || targetClient.metadata.entity_type || 'individual');
        urlParams.append('meta_signature_type', existingDraft.meta_signature_type || targetClient.metadata.signature_type || 'single');
        urlParams.append('meta_co_signer_name', existingDraft.meta_co_signer_name || targetClient.metadata.co_signer_name || '');
        urlParams.append('delivery_format', existingDraft.delivery_format || targetClient.delivery_format || 'electronic');

        // Copy Service Rows from Source
        sourceDraft.rows.forEach((r, idx) => {
            const rid = idx + 1;
            urlParams.append('selected_rows', rid);
            urlParams.append(`row_item_id_${rid}`, r.item_id);
            urlParams.append(`row_service_${rid}`, r.service);
            urlParams.append(`row_fee_${rid}`, Math.round(parseFloat(r.fee || 0)));
            urlParams.append(`row_notes_${rid}`, r.notes || '');
            urlParams.append(`row_bp_${rid}`, r.bp || 'individual');
        });

        // Copy Out-of-Scope Items from Source
        if (sourceDraft.out_of_scope_items) {
            Object.keys(sourceDraft.out_of_scope_items).forEach(k => {
                urlParams.append(k, sourceDraft.out_of_scope_items[k]);
            });
        }

        try {
            const resp = await fetch(window.location.href, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest' 
                },
                body: urlParams
            });

            if (resp.ok) {
                const resData = await resp.json();
                if (resData.status === 'success' && resData.draft) {
                    // Update in-memory draft state
                    targetClient.saved_draft = resData.draft;
                    terminalLog.innerHTML += `SUCCESS ✓`;
                } else {
                    terminalLog.innerHTML += `FAILED ❌ (${resData.message || 'Error'})`;
                }
            } else {
                terminalLog.innerHTML += `FAILED ❌ (HTTP ${resp.status})`;
            }
        } catch (err) {
            terminalLog.innerHTML += `ERROR ❌ (${err.message})`;
        }

        completed++;
        progressBar.style.width = `${(completed / checkedCheckboxes.length) * 100}%`;
        terminalLog.scrollTop = terminalLog.scrollHeight;

        if (completed < checkedCheckboxes.length && BATCH_THROTTLE_DELAY_MS > 0) {
            await sleep(BATCH_THROTTLE_DELAY_MS);
        }
    }

    terminalLog.innerHTML += `\n\n========================================\nScope clone execution complete!`;
    doneBtn.style.display = 'inline-block';

    // Refresh Batch Dashboard grid with updated fee totals and readiness states
    renderBatchTableGrid();
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
        const uniqueId = `custom_${Date.now()}`;
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
function injectHiddenMasterContext(signatureType, entityType, coSignerName, addr, healLegalName) {
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
        <input type="hidden" name="heal_legal_name" value="${escapeHtml(healLegalName || '')}">
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

    // Ensure clone toolbar resets when switching active client
    toggleInlineCopyBar(false);
    
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

    // Decode HTML entities (e.g., &amp; -> &) before parsing name (handles both <input> and <select>)
    const rawText = clientSelect.value || (clientSelect.options && clientSelect.selectedIndex >= 0 ? clientSelect.options[clientSelect.selectedIndex].text : '');
    const rawOptionText = unescapeHtml(rawText);
    const rawCustomerName = rawOptionText.split(/\s*\(Customer/)[0].trim();

    // Priority hierarchy for state recovery: Preserved Form > Disk Draft
    const hasPreservedHeal = window.preservedHealData && Object.keys(window.preservedHealData).length > 0;
    const healData = hasPreservedHeal ? window.preservedHealData : draftData;

    const defaultLegalName = healData.heal_legal_name || rawCustomerName;

    // Render locked banner if agreement was already dispatched
    if (isLocked && lockBannerContainer) {
        lockBannerContainer.style.display = 'block';
        lockBannerContainer.innerHTML = `
            <div class="lock-banner-card">
                <div class="lock-banner-title">🔒 Agreement Dispatched (Read-Only Mode)</div>
                <p class="lock-banner-text">
                    An engagement agreement for <strong>${escapeHtml(defaultLegalName)}</strong> was sent out on <strong>${escapeHtml(lockedMtime)}</strong>. 
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
            renderEditableProfilePanel(profileContainer, address, metadata, rawCustomerName, defaultLegalName, clientRecord.email);
        } else {
            renderReadOnlyProfilePanel(profileContainer, address, metadata, rawCustomerName, defaultLegalName, clientRecord.email);
            injectHiddenMasterContext(metadata.signature_type, metadata.entity_type, metadata.co_signer_name, address, defaultLegalName);
        }
    }

    if (submitBtn) {
        submitBtn.innerText = isLocked ? 'View Sent Agreement (Read-Only)' : 'Render PDF Preview';
        submitBtn.style.display = 'block';
    }

    table.style.display = 'table';
    actionsDiv.style.display = isLocked ? 'none' : 'flex';
    if (outOfScopeContainer) outOfScopeContainer.style.display = 'block';

    const dateSelect = document.getElementById('estimate-date-option');
    if (dateSelect) {
        if (healData.estimate_date_option) dateSelect.value = healData.estimate_date_option;
        dateSelect.disabled = isLocked;
    }

    // Populate preserved field states
    ['friendly_name', 'heal_legal_name', 'heal_street', 'heal_city', 'heal_state', 'heal_zip', 'meta_co_signer_name'].forEach(fieldName => {
        const input = document.querySelector(`input[name="${fieldName}"]`);
        if (input && healData[fieldName]) input.value = healData[fieldName];
    });

    const hEntity = document.querySelector('select[name="meta_entity_type"]');
    if (hEntity && healData.meta_entity_type) hEntity.value = healData.meta_entity_type;

    // Map meta_additional_signer ONLY if present, never overwrite with meta_signature_type
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
function renderEditableProfilePanel(container, addr, meta, defaultFriendlyName, defaultLegalName, clientEmail) {
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
                    <input type="text" name="friendly_name" value="${escapeHtml(unescapeHtml(defaultFriendlyName))}" required placeholder="e.g., Susan Smith">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Legal Name (For Documents)</label>
                    <input type="text" name="heal_legal_name" value="${escapeHtml(unescapeHtml(defaultLegalName))}" required placeholder="e.g., Susan Smith LLC">
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
function renderReadOnlyProfilePanel(container, addr, meta, defaultFriendlyName, defaultLegalName, clientEmail) {
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
            <div style="margin-bottom: 15px; display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div class="form-field-group">
                    <label class="field-label" style="font-weight: 600; font-size: 13px; margin-bottom: 4px;">Friendly Name (Override text if needed)</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(unescapeHtml(defaultFriendlyName))}" style="width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px;" required>
                </div>
                <div class="form-field-group">
                    <label class="field-label" style="font-weight: 600; font-size: 13px; margin-bottom: 4px;">Legal Name (Document Override)</label>
                    <input type="text" name="heal_legal_name" value="${escapeHtml(unescapeHtml(defaultLegalName))}" style="width: 100%; padding: 8px; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px;" required>
                </div>
            </div>
            <div class="profile-grid-layout markdown-verified-grid">
                <div><strong>Billing Address:</strong><br><span style="color:#555;">${escapeHtml(formattedAddress)}</span></div>
                <div><strong>Email:</strong><br><span style="color:#555; font-family: monospace; font-size: 12px;">${clientEmail ? escapeHtml(clientEmail) : '[None Sourced]'}</span></div>
                <div><strong>Classification:</strong><br><span class="badge ${isOrg ? 'badge-organization' : 'badge-individual'}">${escapeHtml(displayClassification)}</span></div>
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
    const legalInput = document.querySelector('input[name="heal_legal_name"]');
    
    const rawText = selectEl.value || (selectEl.options && selectEl.selectedIndex >= 0 ? selectEl.options[selectEl.selectedIndex].text : '');
    const rawOptionText = unescapeHtml(rawText);
    const rawCustomerName = rawOptionText.split(/\s*\(Customer/)[0].trim();

    const defaultFriendlyName = friendlyInput ? friendlyInput.value : rawCustomerName;
    const defaultLegalName = legalInput ? legalInput.value : rawCustomerName;

    renderEditableProfilePanel(container, record.address || {}, record.metadata || {}, defaultFriendlyName, defaultLegalName, record.email);
    
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
                    const wholeFee = Math.round(parseFloat(svc.fee || 0));
                    optionsHtml += `<option value="${svc.id}" data-type="${svc.type}" data-fee="${wholeFee}">${escapeHtml(svc.name)}</option>`;
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

    const feeValue = rowData ? Math.round(parseFloat(rowData.fee || 0)) : '0';
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
            const wholeFee = Math.round(parseFloat(svc.fee || 0));
            optionsHtml += `<option value="${svc.id}" data-type="${svc.type}" data-fee="${wholeFee}" ${isSelected}>${escapeHtml(svc.name)}</option>`;
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
                $ <input type="number" name="row_fee_${currentId}" id="row_fee_${currentId}" step="1" min="-99999" value="${escapeHtml(feeValue)}" oninput="calculateGridTotals()" style="width: 90px; padding: 6px;" required ${disabledAttr}>
            </span>
        </td>
        <td class="notes-cell">
            <textarea name="row_notes_${currentId}" placeholder="Enter custom line parameters or scope exclusions..." style="width: 98%; height: 46px; font-family: inherit; font-size: 13px; padding: 6px; box-sizing: border-box;" ${disabledAttr}>${escapeHtml(notesValue)}</textarea>
        </td>
    `;

    tbody.appendChild(tr);
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
    const feeInput = document.getElementById(`row_fee_${id}`);
    
    if (!selectedOption || selectEl.value === "") {
        if (badgeContainer) badgeContainer.innerHTML = '';
        if (bpInput) bpInput.value = 'individual';
        if (svcNameInput) svcNameInput.value = '';
        if (notesTextarea) notesTextarea.value = '';
        if (feeInput) feeInput.value = '0';
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

    if (!bypassDefaultNotes) {
        const defaultFee = selectedOption.getAttribute('data-fee') || '0';
        if (feeInput) feeInput.value = (defaultFee !== undefined && defaultFee !== null && defaultFee !== '') ? defaultFee : '0';

        if (notesTextarea && selectedClient && window.clientData && window.clientData[selectedClient]) {
            const exposedServices = window.clientData[selectedClient].exposed_services || [];
            const serviceMatch = exposedServices.find(svc => svc.name === itemName);
            notesTextarea.value = serviceMatch ? (serviceMatch.notes || '') : '';
        }
    }

    calculateGridTotals();
}

/**
 * Compiles live financial totals for display in table footer (whole numbers only).
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

    // Render clean whole dollar amounts with thousands separators
    if (discountNode) discountNode.innerText = discountAmount > 0 ? `-$${Math.round(discountAmount).toLocaleString()}` : `$0`;
    if (balanceNode) balanceNode.innerText = `$${Math.round(totalNet).toLocaleString()}`;
}

/* ==========================================================================
   BATCH DASHBOARD & DUAL-MODE ORCHESTRATOR EXTENSION
   ========================================================================== */

let activeModalQboId = null;

/**
 * Toggles between 'On-Demand Intake' mode and 'Seasonal Batch' mode.
 */
function switchWorkspaceMode(mode) {
    const singleView = document.getElementById('single-client-workspace');
    const batchView = document.getElementById('batch-dashboard-workspace');
    const tabSingle = document.getElementById('tab-btn-single');
    const tabBatch = document.getElementById('tab-btn-batch');

    if (mode === 'batch') {
        if (singleView) singleView.style.display = 'none';
        if (batchView) batchView.style.display = 'block';
        if (tabSingle) tabSingle.classList.remove('active');
        if (tabBatch) tabBatch.classList.add('active');
        renderBatchTableGrid();
    } else {
        if (batchView) batchView.style.display = 'none';
        if (singleView) singleView.style.display = 'block';
        if (tabBatch) tabBatch.classList.remove('active');
        if (tabSingle) tabSingle.classList.add('active');
    }
}

/**
 * Builds the batch data grid table using clientData and saved_drafts,
 * analyzing client JSON readiness and preserving user manual selections.
 */
function renderBatchTableGrid() {
    const tbody = document.getElementById('batch-tbody');
    if (!tbody || !window.clientData) return;

    // Preserve user manual checkbox states prior to re-render
    const currentSelections = {};
    document.querySelectorAll('.batch-checkbox').forEach(cb => {
        const id = cb.getAttribute('data-qbo-id');
        if (id) {
            currentSelections[id] = cb.checked;
        }
    });

    tbody.innerHTML = '';

    Object.keys(window.clientData).forEach(clientKey => {
        const client = window.clientData[clientKey];
        const draft = client.saved_draft || {};
        const qboId = client.id;
        const meta = client.metadata || {};
        const clientAddr = client.address || {};
        const isLocked = Boolean(draft.is_locked);
        
        // Sourced delivery_format (defaulting to 'electronic' if not present)
        const rawFormat = (draft.delivery_format || client.delivery_format || 'electronic').toLowerCase();
        const isPaper = rawFormat.includes('paper');
        
        // Calculate Total Fees
        let clientFee = 0.0;
        if (draft.rows && draft.rows.length > 0) {
            draft.rows.forEach(r => { clientFee += parseFloat(r.fee || 0); });
        }

        // Priority check: Use draft healed values if present, fallback to raw QBO record (defensive object lookup)
        const street = draft.heal_street || clientAddr.street || '';
        const city = draft.heal_city || clientAddr.city || '';
        const entityType = draft.meta_entity_type || meta.entity_type;
        const email = client.email;

        // Comprehensive Readiness Evaluation:
        // 1. JSON Exists: draft object must exist and contain at least one valid row
        const isJsonPresent = Boolean(client.saved_draft && Object.keys(client.saved_draft).length > 0);
        const hasServiceRows = Boolean(draft.rows && Array.isArray(draft.rows) && draft.rows.length > 0);
        
        // 2. Required Fields present: address, entity type, email
        const isAddressMissing = !street || !city;
        const isConfigMissing = !entityType;
        const isEmailMissing = !email;

        const isDataIncomplete = !isJsonPresent || !hasServiceRows || isAddressMissing || isConfigMissing || isEmailMissing;

        let statusBadge = '<span class="badge badge-electronic">Ready</span>';
        let checkboxDisabled = '';

        if (isLocked) {
            statusBadge = '<span class="badge badge-locked">🔒 Sent</span>';
            checkboxDisabled = 'disabled';
        } else if (isDataIncomplete) {
            statusBadge = '<span class="badge badge-warning">⚠️ Data Incomplete</span>';
            checkboxDisabled = 'disabled';
        }

        // Use saved selection state if present; otherwise default to ready condition
        let isChecked = false;
        if (Object.prototype.hasOwnProperty.call(currentSelections, qboId)) {
            isChecked = currentSelections[qboId];
        } else {
            isChecked = (!isLocked && !isDataIncomplete);
        }

        const checkedAttr = isChecked ? 'checked' : '';

        // Interactive Format Badge (Click to Toggle Paper vs Electronic)
        const formatBadgeClass = isPaper ? 'badge-paper' : 'badge-electronic';
        const formatText = isPaper ? 'Paper' : 'Electronic';
        const disabledCursor = isLocked ? 'cursor: default;' : 'cursor: pointer;';
        
        const formatBadgeHtml = `
            <span class="badge ${formatBadgeClass}" 
                  onclick="${isLocked ? '' : `toggleClientDeliveryFormat('${qboId}')`}" 
                  title="${isLocked ? 'Locked' : 'Click to toggle delivery format'}" 
                  style="${disabledCursor} user-select: none;">
                ${formatText} 🔄
            </span>
        `;

        const tr = document.createElement('tr');
        tr.id = `batch_row_${qboId}`;
        tr.className = `batch-row-item format-${isPaper ? 'paper' : 'electronic'}`;
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="batch-checkbox" data-qbo-id="${qboId}" ${checkboxDisabled} ${checkedAttr} onchange="updateBatchSummaryMetrics()">
            </td>
            <td style="font-family: monospace; font-size: 12px; color: #555;">${qboId}</td>
            <td>
                <strong>${escapeHtml(draft.friendly_name || clientKey.split(' (Customer')[0])}</strong>
                <br/><small style="color: #666;">${escapeHtml(draft.heal_legal_name || '')}</small>
            </td>
            <td><span class="badge ${entityType === 'individual' ? 'badge-individual' : 'badge-organization'}">${escapeHtml(entityType || 'individual')}</span></td>
            <td style="font-size: 12px; color: #444;">${meta.signature_type && meta.signature_type.includes('@') ? 'Joint (' + escapeHtml(meta.co_signer_name) + ')' : 'Single'}</td>
            <td style="text-align: right; font-family: monospace; font-weight: bold; font-size: 14px;">$${Math.round(clientFee).toLocaleString()}</td>
            <td>${formatBadgeHtml}</td>
            <td>${statusBadge}</td>
            <td style="text-align: center;">
                <button type="button" class="btn-add-row" onclick="openBatchEditModal('${qboId}')" style="padding: 4px 10px; font-size: 12px;">✏️ Edit</button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    updateBatchSummaryMetrics();
}

/**
 * Toggles a client's delivery format (Paper <-> Electronic) directly in the Batch Grid,
 * updates memory, re-renders the row, and saves the setting to disk via AJAX.
 */
async function toggleClientDeliveryFormat(qboId) {
    const clientKey = Object.keys(window.clientData).find(k => window.clientData[k].id === qboId);
    if (!clientKey) return;

    const client = window.clientData[clientKey];
    client.saved_draft = client.saved_draft || {};

    const currentFmt = (client.saved_draft.delivery_format || client.delivery_format || 'electronic').toLowerCase();
    const newFmt = currentFmt.includes('paper') ? 'electronic' : 'paper';

    // 1. Update browser memory state
    client.saved_draft.delivery_format = newFmt;
    client.delivery_format = newFmt;

    // 2. Refresh UI Grid immediately
    renderBatchTableGrid();

    // 3. Persist new choice to disk via AJAX
    const urlParams = new URLSearchParams();
    urlParams.append('action', 'save_draft_only');
    urlParams.append('ajax', 'true'); // Explicit AJAX flag
    urlParams.append('client_name', clientKey);
    urlParams.append('delivery_format', newFmt);

    // Pass existing draft parameters so nothing gets wiped
    const draft = client.saved_draft;
    urlParams.append('friendly_name', draft.friendly_name || '');
    urlParams.append('heal_legal_name', draft.heal_legal_name || '');
    urlParams.append('meta_entity_type', draft.meta_entity_type || 'individual');
    urlParams.append('meta_signature_type', draft.meta_signature_type || 'single');
    urlParams.append('meta_co_signer_name', draft.meta_co_signer_name || '');

    if (draft.rows) {
        draft.rows.forEach((r, idx) => {
            const rid = idx + 1;
            urlParams.append('selected_rows', rid);
            urlParams.append(`row_item_id_${rid}`, r.item_id);
            urlParams.append(`row_service_${rid}`, r.service);
            urlParams.append(`row_fee_${rid}`, Math.round(parseFloat(r.fee || 0)));
            urlParams.append(`row_notes_${rid}`, r.notes || '');
            urlParams.append(`row_bp_${rid}`, r.bp || 'individual');
        });
    }

    if (draft.out_of_scope_items) {
        Object.keys(draft.out_of_scope_items).forEach(k => {
            urlParams.append(k, draft.out_of_scope_items[k]);
        });
    }

    try {
        await fetch(window.location.href, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: urlParams
        });
    } catch (err) {
        console.error("Failed to persist delivery_format override:", err);
    }
}

/**
 * Updates selected row counter and total fees in table footer summary.
 */
function updateBatchSummaryMetrics() {
    const checkedBoxes = document.querySelectorAll('.batch-checkbox:checked');
    let totalFee = 0.0;
    let electronicCount = 0;
    let paperCount = 0;

    checkedBoxes.forEach(cb => {
        const qboId = cb.getAttribute('data-qbo-id');
        const clientKey = Object.keys(window.clientData).find(k => window.clientData[k].id === qboId);
        if (clientKey) {
            const client = window.clientData[clientKey];
            const draft = client.saved_draft || {};
            const isPaper = (draft.delivery_format || client.delivery_format || 'electronic').toLowerCase().includes('paper');
            
            if (isPaper) paperCount++; else electronicCount++;

            if (draft.rows) {
                draft.rows.forEach(r => { totalFee += parseFloat(r.fee || 0); });
            }
        }
    });

    const summaryNode = document.getElementById('batch-summary-bar');
    if (summaryNode) {
        summaryNode.innerHTML = `
            <strong>Selected:</strong> ${checkedBoxes.length} client(s) &nbsp;|&nbsp;
            <strong>Electronic:</strong> ${electronicCount} &nbsp;|&nbsp;
            <strong>Paper:</strong> ${paperCount} &nbsp;|&nbsp;
            <strong>Batch Total:</strong> $${Math.round(totalFee).toLocaleString()}
        `;
    }
}

/**
 * Filter batch grid table by text search and delivery format.
 */
function filterBatchTableGrid() {
    const searchQuery = (document.getElementById('batch-search-input')?.value || '').toLowerCase();
    const formatFilter = document.getElementById('batch-format-filter')?.value || 'all';

    document.querySelectorAll('#batch-tbody tr').forEach(tr => {
        const text = tr.innerText.toLowerCase();
        const isPaper = tr.classList.contains('format-paper');
        
        const matchesSearch = text.includes(searchQuery);
        let matchesFormat = true;
        if (formatFilter === 'paper') matchesFormat = isPaper;
        if (formatFilter === 'electronic') matchesFormat = !isPaper;

        tr.style.display = (matchesSearch && matchesFormat) ? '' : 'none';
    });
}

/**
 * Select or Deselect all non-disabled rows in batch view.
 */
function selectAllBatchRows(shouldSelect) {
    document.querySelectorAll('.batch-checkbox:not([disabled])').forEach(cb => {
        cb.checked = shouldSelect;
    });
    updateBatchSummaryMetrics();
}

/**
 * Opens the Modal Popup editor to inspect/modify a single client draft.
 */
function openBatchEditModal(qboId) {
    activeModalQboId = qboId;
    const clientKey = Object.keys(window.clientData).find(k => window.clientData[k].id === qboId);
    if (!clientKey) return;

    const modal = document.getElementById('batch-edit-modal');
    const modalContentContainer = document.getElementById('modal-workspace-container');
    const clientSelect = document.getElementById('client-select');

    if (clientSelect) {
        clientSelect.value = clientKey;
        onClientChange();
    }

    // Move working form components into modal workspace container
    modalContentContainer.appendChild(document.getElementById('profile-healing-container'));
    modalContentContainer.appendChild(document.getElementById('service-table'));
    modalContentContainer.appendChild(document.getElementById('actions-container'));
    modalContentContainer.appendChild(document.getElementById('out-of-scope-container'));

    document.getElementById('modal-client-title').innerText = `Edit Draft — ${clientKey.split(' (Customer')[0]}`;
    modal.style.display = 'flex';
}

/**
 * Helper: Safely returns interactive DOM form components back to the single-client workspace container.
 */
function returnElementsToSingleWorkspace() {
    const singleForm = document.querySelector('#single-client-workspace form');
    if (singleForm) {
        const profileContainer = document.getElementById('profile-healing-container');
        const serviceTable = document.getElementById('service-table');
        const actionsContainer = document.getElementById('actions-container');
        const oosContainer = document.getElementById('out-of-scope-container');
        const submitContainer = singleForm.querySelector('.submit-container');

        if (submitContainer) {
            singleForm.insertBefore(profileContainer, submitContainer);
            singleForm.insertBefore(serviceTable, submitContainer);
            singleForm.insertBefore(actionsContainer, submitContainer);
            singleForm.insertBefore(oosContainer, submitContainer);
        } else {
            singleForm.appendChild(profileContainer);
            singleForm.appendChild(serviceTable);
            singleForm.appendChild(actionsContainer);
            singleForm.appendChild(oosContainer);
        }
    }
}

/**
 * Discards uncommitted modal edits and closes overlay WITHOUT sending a server update.
 */
function cancelBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    if (!modal) return;

    // Return DOM components back to single workspace without executing background save
    returnElementsToSingleWorkspace();

    modal.style.display = 'none';
    activeModalQboId = null;
    
    // Refresh the batch grid so UI reflects original unedited state
    renderBatchTableGrid();
}

/**
 * Explicitly saves modal inputs to disk via AJAX, updates client memory, and returns elements to document flow.
 */
async function closeBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    const clientSelect = document.getElementById('client-select');
    const activeClientKey = clientSelect ? clientSelect.value : '';

    // Save modal inputs via background AJAX
    if (activeClientKey && window.clientData[activeClientKey]) {
        const urlParams = new URLSearchParams();
        urlParams.append('action', 'save_draft_only');
        urlParams.append('ajax', 'true'); // Explicit AJAX flag
        urlParams.append('client_name', activeClientKey);

        const estDateSelect = document.getElementById('estimate-date-option');
        if (estDateSelect) urlParams.append('estimate_date_option', estDateSelect.value);

        const friendlyInput = document.querySelector('input[name="friendly_name"]');
        const legalInput = document.querySelector('input[name="heal_legal_name"]');
        const entitySelect = document.querySelector('select[name="meta_entity_type"]');
        const sigInput = document.querySelector('input[name="meta_additional_signer"]');
        const coSignerInput = document.querySelector('input[name="meta_co_signer_name"]');
        const streetInput = document.querySelector('input[name="heal_street"]');
        const cityInput = document.querySelector('input[name="heal_city"]');
        const stateInput = document.querySelector('input[name="heal_state"]');
        const zipInput = document.querySelector('input[name="heal_zip"]');
        const healFlagInput = document.querySelector('input[name="heal_profile_flag"]');

        if (friendlyInput) urlParams.append('friendly_name', friendlyInput.value);
        if (legalInput) urlParams.append('heal_legal_name', legalInput.value);
        if (entitySelect) urlParams.append('meta_entity_type', entitySelect.value);
        if (sigInput) urlParams.append('meta_additional_signer', sigInput.value);
        if (coSignerInput) urlParams.append('meta_co_signer_name', coSignerInput.value);
        if (streetInput) urlParams.append('heal_street', streetInput.value);
        if (cityInput) urlParams.append('heal_city', cityInput.value);
        if (stateInput) urlParams.append('heal_state', stateInput.value);
        if (zipInput) urlParams.append('heal_zip', zipInput.value);
        if (healFlagInput) urlParams.append('heal_profile_flag', healFlagInput.value);

        // Preserve delivery_format preference
        const currentDraft = window.clientData[activeClientKey].saved_draft || {};
        const currentFmt = currentDraft.delivery_format || window.clientData[activeClientKey].delivery_format || 'electronic';
        urlParams.append('delivery_format', currentFmt);

        // Gather Service Rows
        document.querySelectorAll('input[name="selected_rows"]').forEach(r => {
            const rid = r.value;
            const itemSelect = document.querySelector(`select[name="row_item_id_${rid}"]`);
            const feeInput = document.getElementById(`row_fee_${rid}`);
            const notesInput = document.querySelector(`textarea[name="row_notes_${rid}"]`);
            const bpInput = document.getElementById(`row_bp_${rid}`);
            const svcInput = document.getElementById(`row_service_${rid}`);

            if (itemSelect && itemSelect.value) {
                urlParams.append('selected_rows', rid);
                urlParams.append(`row_item_id_${rid}`, itemSelect.value);
                urlParams.append(`row_service_${rid}`, svcInput ? svcInput.value : '');
                urlParams.append(`row_fee_${rid}`, feeInput ? Math.round(parseFloat(feeInput.value || 0)) : '0');
                urlParams.append(`row_notes_${rid}`, notesInput ? notesInput.value : '');
                urlParams.append(`row_bp_${rid}`, bpInput ? bpInput.value : 'individual');
            }
        });

        // Gather Out-of-Scope Items
        const oosContainer = document.getElementById('out-of-scope-checklist-container');
        if (oosContainer) {
            oosContainer.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
                urlParams.append(cb.name, cb.value);
            });
        }

        try {
            const response = await fetch(window.location.href, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: urlParams
            });
            if (response.ok) {
                const resData = await response.json();
                if (resData.status === 'success' && resData.draft) {
                    // Update browser memory state with newly written draft
                    window.clientData[activeClientKey].saved_draft = resData.draft;
                    if (resData.draft.meta_entity_type) {
                        window.clientData[activeClientKey].metadata = window.clientData[activeClientKey].metadata || {};
                        window.clientData[activeClientKey].metadata.entity_type = resData.draft.meta_entity_type;
                    }
                }
            }
        } catch (err) {
            console.error("Failed to execute background draft save:", err);
        }
    }

    const activeQboId = activeModalQboId;

    // Return DOM components back to single-client workspace
    returnElementsToSingleWorkspace();

    modal.style.display = 'none';
    activeModalQboId = null;
    
    // Refresh the batch table grid to reflect updated total fees and saved state
    renderBatchTableGrid();

    // If edited row is now valid/ready, ensure its checkbox becomes checked
    if (activeQboId) {
        const editedCb = document.querySelector(`.batch-checkbox[data-qbo-id="${activeQboId}"]`);
        if (editedCb && !editedCb.disabled) {
            editedCb.checked = true;
            updateBatchSummaryMetrics();
        }
    }
}

/**
 * Iterates sequentially through selected rows and submits payloads via Fetch/AJAX.
 */
async function executeBatchPipelineSubmission() {
    const selectedCheckboxes = document.querySelectorAll('.batch-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        alert("Please select at least one client to process.");
        return;
    }

    if (!confirm(`Are you sure you want to process and dispatch ${selectedCheckboxes.length} client engagement(s)?`)) return;

    const progressOverlay = document.getElementById('batch-progress-overlay');
    const progressBar = document.getElementById('batch-progress-fill');
    const terminalLog = document.getElementById('batch-terminal-log');
    const doneBtn = document.getElementById('btn-close-progress');

    progressOverlay.style.display = 'flex';
    doneBtn.style.display = 'none';
    terminalLog.innerHTML = `Starting batch process for ${selectedCheckboxes.length} client(s)...\n`;

    let completed = 0;

    for (const cb of selectedCheckboxes) {
        const qboId = cb.getAttribute('data-qbo-id');
        const clientKey = Object.keys(window.clientData).find(k => window.clientData[k].id === qboId);
        const client = window.clientData[clientKey];
        const draft = client.saved_draft || {};
        
        const isPaper = (draft.delivery_format || client.delivery_format || 'electronic').toLowerCase().includes('paper');
        const targetAction = isPaper ? 'execute_transactional_pipeline_paper' : 'execute_transactional_pipeline';

        terminalLog.innerHTML += `\n[${completed + 1}/${selectedCheckboxes.length}] Processing QBO ID ${qboId} (${isPaper ? 'PAPER' : 'E-SIGN'})... `;

        const urlParams = new URLSearchParams();
        urlParams.append('action', targetAction);
        urlParams.append('ajax', 'true'); // Explicit AJAX flag
        urlParams.append('client_name', clientKey);
        urlParams.append('delivery_method', isPaper ? 'paper' : '');

        urlParams.append('friendly_name', draft.friendly_name || '');
        urlParams.append('heal_legal_name', draft.heal_legal_name || '');
        urlParams.append('meta_entity_type', draft.meta_entity_type || 'individual');
        urlParams.append('meta_signature_type', draft.meta_signature_type || 'single');
        urlParams.append('meta_co_signer_name', draft.meta_co_signer_name || '');

        if (draft.rows) {
            draft.rows.forEach((r, idx) => {
                const rid = idx + 1;
                urlParams.append('selected_rows', rid);
                urlParams.append(`row_item_id_${rid}`, r.item_id);
                urlParams.append(`row_service_${rid}`, r.service);
                urlParams.append(`row_fee_${rid}`, Math.round(parseFloat(r.fee || 0)));
                urlParams.append(`row_notes_${rid}`, r.notes || '');
                urlParams.append(`row_bp_${rid}`, r.bp || 'individual');
            });
        }

        if (draft.out_of_scope_items) {
            Object.keys(draft.out_of_scope_items).forEach(k => {
                urlParams.append(k, draft.out_of_scope_items[k]);
            });
        }

        try {
            const resp = await fetch(window.location.href, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest' 
                },
                body: urlParams
            });

            if (resp.ok) {
                const resData = await resp.json();
                if (resData.status === 'success') {
                    terminalLog.innerHTML += `SUCCESS ✓ (Estimate #${resData.estimate_id})`;
                } else {
                    terminalLog.innerHTML += `FAILED ❌ (${resData.message || 'Unknown error'})`;
                }
            } else {
                let errorDetails = `HTTP ${resp.status}`;
                try {
                    const errData = await resp.json();
                    if (errData.message) errorDetails = errData.message;
                } catch (e) {
                    // Not JSON error body
                }
                terminalLog.innerHTML += `FAILED ❌ (${errorDetails})`;
            }
        } catch (err) {
            terminalLog.innerHTML += `ERROR ❌ (${err.message})`;
        }

        completed++;
        progressBar.style.width = `${(completed / selectedCheckboxes.length) * 100}%`;
        terminalLog.scrollTop = terminalLog.scrollHeight;

        // Apply configurable throttle pause between API calls (skips after last item)
        if (completed < selectedCheckboxes.length && BATCH_THROTTLE_DELAY_MS > 0) {
            await sleep(BATCH_THROTTLE_DELAY_MS);
        }
    }

    terminalLog.innerHTML += `\n\n========================================\nBatch execution complete!`;
    doneBtn.style.display = 'inline-block';
}

// Global Form Submit Safeguard & Key Listener
document.addEventListener('DOMContentLoaded', () => {
    // Audit Python App Config to toggle Batch interface visibility
    const isBatchEnabled = Boolean(window.APP_CONFIG && window.APP_CONFIG.enableBatchMode === true);
    const modeTabsContainer = document.querySelector('.mode-tabs');

    if (!isBatchEnabled) {
        if (modeTabsContainer) {
            modeTabsContainer.classList.add('mode-tabs-hidden');
            modeTabsContainer.style.display = 'none';
        }
        switchWorkspaceMode('single');
    }

    const form = document.querySelector('form');
    if (form) {
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
            if (action === 'revert_to_workspace' || action === 'save_draft_only') return true;

            const clientSelect = document.getElementById('client-select');
            if (!clientSelect || !clientSelect.value) return true;

            const clientRecord = window.clientData[clientSelect.value];
            if (clientRecord && clientRecord.saved_draft && clientRecord.saved_draft.is_locked) return true;

            const addSignerInput = document.querySelector('input[name="meta_additional_signer"]');
            const coSignerNameInput = document.querySelector('input[name="meta_co_signer_name"]');

            const CLEAR_KEYWORDS = ["none", "null", "single", "n/a"];
            const hasEmail = addSignerInput && addSignerInput.value.trim() !== "" && !CLEAR_KEYWORDS.includes(addSignerInput.value.trim().toLowerCase());
            const hasName = coSignerNameInput && coSignerNameInput.value.trim() !== "" && !CLEAR_KEYWORDS.includes(coSignerNameInput.value.trim().toLowerCase());

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
    }

    // Keyboard Escape key shortcut cancels modal without saving
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeModalQboId) {
            cancelBatchEditModal();
        }
    });

    // Clicking outside the modal card cancels without saving
    window.addEventListener('click', (e) => {
        const modal = document.getElementById('batch-edit-modal');
        if (e.target === modal && activeModalQboId) {
            cancelBatchEditModal();
        }
    });
});
