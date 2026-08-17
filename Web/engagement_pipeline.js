/**
 * 2026 Engagement Utility Front-End Orchestrator
 * Clean Modern Architecture — Standardized Dictionary Schema
 */

let rowCounter = 0;

// Global Configuration
const BATCH_THROTTLE_DELAY_MS = 500;

// Centralized Entity Classification Configuration
const ORGANIZATION_ENTITY_TYPES = ['sm_llc', 's_corp', 'partnership', 'c_corp', 'non_profit', 'trust'];

const ENTITY_DISPLAY_NAMES = {
    'individual': 'Individual',
    'sm_llc': 'Single Member LLC',
    's_corp': 'S-Corporation',
    'partnership': 'Partnership',
    'c_corp': 'C-Corporation',
    'non_profit': 'Tax-Exempt Org',
    'trust': 'Trust / Estate'
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function unescapeHtml(str) {
    if (!str) return '';
    const txt = document.createElement('textarea');
    txt.innerHTML = str;
    return txt.value;
}

// Toggle Email Composer Accordion in Phase 2 Editor Panel
window.toggleEmailComposer = function toggleEmailComposer() {
    const el = document.getElementById("email-composer-fields");
    if (!el) return;

    // Check computed style to reliably toggle regardless of inline or CSS rules
    const currentDisplay = window.getComputedStyle(el).display;
    if (currentDisplay === "none") {
        el.style.display = "block";
    } else {
        el.style.display = "none";
    }
}

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

function applyClonedScopeFromSource() {
    const sourceInput = document.getElementById('clone-source-input');
    const targetSelect = document.getElementById('client-select');

    if (!sourceInput || !targetSelect || !sourceInput.value) {
        alert("Please select a valid source engagement to copy scope from.");
        return;
    }

    const sourceVal = sourceInput.value.trim();
    const parts = sourceVal.split(':');
    if (parts.length < 2) {
        alert("Invalid source engagement specification.");
        return;
    }
    
    const srcQboId = parts[0];
    const srcEngId = parts[1];

    let sourceDraft = null;
    if (window.clientData) {
        Object.keys(window.clientData).forEach(clientKey => {
            const client = window.clientData[clientKey];
            if (String(client.id) === String(srcQboId) && client.engagements && client.engagements[srcEngId]) {
                sourceDraft = client.engagements[srcEngId];
            }
        });
    }

    if (!sourceDraft || !sourceDraft.rows || sourceDraft.rows.length === 0) {
        alert("Selected source engagement file has no saved service offerings to copy.");
        return;
    }

    const tbody = document.getElementById('service-tbody');
    const existingRows = tbody ? tbody.querySelectorAll('tr') : [];
    if (existingRows.length > 0) {
        if (!confirm("Applying scope from source engagement will replace current line items and out-of-scope selections in this workspace. Continue?")) {
            return;
        }
    }

    if (tbody) tbody.innerHTML = '';
    rowCounter = 0;

    sourceDraft.rows.forEach(row => {
        addServiceRow(row, false);
    });

    if (sourceDraft.out_of_scope_items) {
        rehydrateOutOfScopeItems(sourceDraft.out_of_scope_items, false);
    }

    if (sourceDraft.estimate_date_option) {
        const estDateSelect = document.getElementById('estimate-date-option');
        if (estDateSelect) estDateSelect.value = sourceDraft.estimate_date_option;
    }

    calculateGridTotals();
    toggleInlineCopyBar(false);
}

async function applyBatchBulkClonedScope() {
    const sourceInput = document.getElementById('batch-bulk-source-input');
    const checkedCheckboxes = document.querySelectorAll('.batch-checkbox:checked');

    if (!sourceInput || !sourceInput.value) {
        alert("Please select a valid source engagement.");
        return;
    }

    if (checkedCheckboxes.length === 0) {
        alert("Please select at least one batch engagement to receive the cloned scope.");
        return;
    }

    const sourceVal = sourceInput.value.trim();
    const parts = sourceVal.split(':');
    if (parts.length < 2) {
        alert("Invalid source engagement selection.");
        return;
    }
    const srcQboId = parts[0];
    const srcEngId = parts[1];

    let sourceDraft = null;
    let sourceClientKey = "";
    if (window.clientData) {
        Object.keys(window.clientData).forEach(clientKey => {
            const client = window.clientData[clientKey];
            if (String(client.id) === String(srcQboId) && client.engagements && client.engagements[srcEngId]) {
                sourceDraft = client.engagements[srcEngId];
                sourceClientKey = clientKey;
            }
        });
    }

    if (!sourceDraft || !sourceDraft.rows || sourceDraft.rows.length === 0) {
        alert("Selected source engagement file has no saved service offerings to copy.");
        return;
    }

    if (!confirm(`Apply cloned scope (${sourceDraft.rows.length} item(s)) to ${checkedCheckboxes.length} checked batch engagement(s)?`)) {
        return;
    }

    toggleBatchBulkCopyToolbar(false);

    const progressOverlay = document.getElementById('batch-progress-overlay');
    const progressBar = document.getElementById('batch-progress-fill');
    const terminalLog = document.getElementById('batch-terminal-log');
    const doneBtn = document.getElementById('btn-close-progress');

    progressOverlay.style.display = 'flex';
    doneBtn.style.display = 'none';
    terminalLog.innerHTML = `Cloning scope from [${sourceClientKey.split(' (Customer')[0]} - ${sourceDraft.engagement_title || 'Engagement'}] to ${checkedCheckboxes.length} engagement file(s)...\n`;

    let completed = 0;

    for (const cb of checkedCheckboxes) {
        const qboId = cb.getAttribute('data-qbo-id');
        const engId = cb.getAttribute('data-eng-id');
        
        const clientKey = Object.keys(window.clientData).find(k => String(window.clientData[k].id) === String(qboId));
        if (!clientKey) continue;

        const targetClient = window.clientData[clientKey];
        const targetEng = (targetClient.engagements && targetClient.engagements[engId]) ? targetClient.engagements[engId] : {};

        terminalLog.innerHTML += `\n[${completed + 1}/${checkedCheckboxes.length}] Applying scope to ${clientKey.split(' (Customer')[0]} (${targetEng.engagement_title || 'Engagement'})... `;

        const syncQboCb = document.getElementById('sync_to_qbo');
        const syncQboVal = syncQboCb ? (syncQboCb.checked ? 'true' : 'false') : 'true';

        const urlParams = new URLSearchParams();
        urlParams.append('action', 'save_draft_only');
        urlParams.append('ajax', 'true');
        urlParams.append('client_name', clientKey);
        urlParams.append('engagement_id', engId);
        urlParams.append('engagement_title', targetEng.engagement_title || '2026 Tax Services Agreement');
        urlParams.append('sync_to_qbo', syncQboVal);

        urlParams.append('estimate_date_option', sourceDraft.estimate_date_option || targetEng.estimate_date_option || 'next_year');
        urlParams.append('friendly_name', (targetEng.primary_signer ? targetEng.primary_signer.friendly_name : '') || targetClient.metadata.friendly_name || clientKey.split(' (Customer')[0]);
        urlParams.append('legal_name', (targetEng.primary_signer ? targetEng.primary_signer.legal_name : '') || clientKey.split(' (Customer')[0]);
        urlParams.append('primary_signer_email', (targetEng.primary_signer ? targetEng.primary_signer.email : '') || targetClient.metadata.primary_signer_email || targetClient.email || '');
        urlParams.append('entity_type', targetEng.entity_type || (targetClient.metadata ? targetClient.metadata.entity_type : 'individual'));
        urlParams.append('co_signer_name', (targetEng.co_signer ? targetEng.co_signer.name : '') || (targetClient.metadata ? targetClient.metadata.co_signer_name : ''));
        urlParams.append('co_signer_email', (targetEng.co_signer ? targetEng.co_signer.email : '') || (targetClient.metadata ? targetClient.metadata.co_signer_email : ''));
        urlParams.append('delivery_format', targetEng.delivery_format || 'electronic');

        sourceDraft.rows.forEach((r, idx) => {
            const rid = idx + 1;
            urlParams.append('selected_rows', rid);
            urlParams.append(`row_item_id_${rid}`, r.item_id);
            urlParams.append(`row_service_${rid}`, r.service);
            urlParams.append(`row_fee_${rid}`, Math.round(parseFloat(r.fee || 0)));
            urlParams.append(`row_notes_${rid}`, r.notes || '');
            urlParams.append(`row_bp_${rid}`, r.bp || 'individual');
        });

        urlParams.append('oos_submitted', 'true');
        if (sourceDraft.out_of_scope_items && typeof sourceDraft.out_of_scope_items === 'object') {
            Object.entries(sourceDraft.out_of_scope_items).forEach(([k, v]) => {
                urlParams.append(k, v);
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
                    targetClient.engagements = targetClient.engagements || {};
                    targetClient.engagements[resData.engagement_id || engId] = resData.draft;
                    terminalLog.innerHTML += `SUCCESS ✔`;
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

    renderBatchTableGrid();
}

function addCustomOutOfScopeItem(customValue = '', customKey = '', isLocked = false) {
    const input = document.getElementById('new-out-of-scope-input');
    const container = document.getElementById('out-of-scope-checklist-container');
    if (!container) return;

    const val = customValue ? customValue.trim() : (input ? input.value.trim() : '');
    if (!val) return;

    const nameAttr = customKey || `custom_${Date.now()}_${Math.floor(Math.random() * 1000)}`;

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

function rehydrateOutOfScopeItems(oosDict = null, isLocked = false) {
    const container = document.getElementById('out-of-scope-checklist-container');
    if (!container) return;

    const isSavedDraft = (oosDict !== null && oosDict !== undefined && typeof oosDict === 'object' && !Array.isArray(oosDict));
    const savedKeys = isSavedDraft ? Object.keys(oosDict) : [];

    const standardInputs = container.querySelectorAll('input[type="checkbox"]:not([name*="custom"])');
    standardInputs.forEach(cb => {
        if (isSavedDraft) {
            cb.checked = savedKeys.includes(cb.name);
        } else {
            cb.checked = true;
        }
        cb.disabled = isLocked;
    });

    container.querySelectorAll('.custom-out-of-scope-item').forEach(el => el.remove());

    if (isSavedDraft) {
        Object.entries(oosDict).forEach(([key, val]) => {
            if (key.includes('custom')) {
                addCustomOutOfScopeItem(val, key, isLocked);
            }
        });
    }
}

function injectHiddenMasterContext(entityType, coSignerName, coSignerEmail, addr, legalName, primaryEmail) {
    let container = document.getElementById('hidden-master-context');
    if (!container) {
        container = document.createElement('div');
        container.id = 'hidden-master-context';
        const table = document.getElementById('service-table');
        if (table && table.parentNode) table.parentNode.appendChild(container);
    }
    addr = addr || {};

    container.innerHTML = `
        <input type="hidden" name="profile_verified" value="false">
        <input type="hidden" name="entity_type" value="${entityType || 'individual'}">
        <input type="hidden" name="co_signer_name" value="${coSignerName || ''}">
        <input type="hidden" name="co_signer_email" value="${coSignerEmail || ''}">
        <input type="hidden" name="legal_name" value="${escapeHtml(legalName || '')}">
        <input type="hidden" name="primary_signer_email" value="${escapeHtml(primaryEmail || '')}">
        <input type="hidden" name="street" value="${addr.street || ''}">
        <input type="hidden" name="city" value="${addr.city || ''}">
        <input type="hidden" name="state" value="${addr.state || ''}">
        <input type="hidden" name="zip" value="${addr.zip || ''}">
    `;
}

function onClientInput() {
    const textInput = document.getElementById('client-select-input');
    const hiddenInput = document.getElementById('client-select');
    const datalist = document.getElementById('client-select-options');
    if (!textInput || !hiddenInput || !datalist) return;

    const val = textInput.value;
    let foundValue = '';

    for (let i = 0; i < datalist.options.length; i++) {
        if (datalist.options[i].value === val) {
            foundValue = datalist.options[i].getAttribute('data-value') || '';
            break;
        }
    }

    hiddenInput.value = foundValue;
    onClientChange();
}

function onClientChange() {
    const clientSelect = document.getElementById('client-select');
    if (!clientSelect) return;

    toggleInlineCopyBar(false);
    
    const selectedVal = clientSelect.value;
    const table = document.getElementById('service-table');
    const tbody = document.getElementById('service-tbody');
    const actionsDiv = document.getElementById('actions-container');
    const outOfScopeContainer = document.getElementById('out-of-scope-container');
    const profileContainer = document.getElementById('profile-healing-container');
    const syncToolbarContainer = document.getElementById('qbo-sync-toolbar-container');
    const lockBannerContainer = document.getElementById('lock-banner-container');
    const activeHeaderBanner = document.getElementById('active-client-header-banner');
    const submitBtn = document.getElementById('btn-submit-main');

    tbody.innerHTML = '';
    if (profileContainer) profileContainer.innerHTML = '';
    if (lockBannerContainer) {
        lockBannerContainer.innerHTML = '';
        lockBannerContainer.style.display = 'none';
    }
    if (activeHeaderBanner) {
        activeHeaderBanner.innerHTML = '';
        activeHeaderBanner.style.display = 'none';
    }
    
    const existingInputs = tbody.querySelectorAll('input[name="selected_rows"]');
    let maxIdx = 0;
    existingInputs.forEach(inp => {
        const val = parseInt(inp.value, 10);
        if (!isNaN(val) && val > maxIdx) maxIdx = val;
    });
    rowCounter = maxIdx;

    if (!selectedVal || selectedVal === "") {
        table.style.display = 'none';
        actionsDiv.style.display = 'none';
        if (outOfScopeContainer) outOfScopeContainer.style.display = 'none';
        if (profileContainer) profileContainer.style.display = 'none';
        if (syncToolbarContainer) syncToolbarContainer.style.display = 'none';
        if (submitBtn) submitBtn.style.display = 'none';
        return;
    }

    const parts = selectedVal.split(':');
    const qboId = parts[0];
    const engId = parts.length > 1 ? parts[1] : '0';

    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    if (!clientKey || !window.clientData[clientKey]) {
        table.style.display = 'none';
        actionsDiv.style.display = 'none';
        if (outOfScopeContainer) outOfScopeContainer.style.display = 'none';
        if (profileContainer) profileContainer.style.display = 'none';
        if (syncToolbarContainer) syncToolbarContainer.style.display = 'none';
        if (submitBtn) submitBtn.style.display = 'none';
        return;
    }

    const clientRecord = window.clientData[clientKey];
    const metadata = clientRecord.metadata || {};
    const address = clientRecord.address || {};
    
    const engagements = clientRecord.engagements || {};
    const isNew = (engId === '0' || !engagements[engId]);
    const draftData = isNew ? { engagement_id: '0', engagement_title: '2026 Tax Services Agreement', rows: [], out_of_scope_items: null } : engagements[engId];

    const isLocked = Boolean(draftData.is_locked);
    const lockedMtime = draftData.locked_mtime || 'recently';

    const rawCustomerName = clientKey.split(/\s*\(Customer/)[0].trim();
    const activeDraft = (window.preservedHealData && Object.keys(window.preservedHealData).length > 0) ? window.preservedHealData : draftData;

    const pSigner = activeDraft.primary_signer || {};
    const coSigner = activeDraft.co_signer || {};
    const addrObj = activeDraft.billing_address || address;

    const defaultLegalName = pSigner.legal_name || activeDraft.legal_name || rawCustomerName;
    const defaultFriendlyName = activeDraft.friendly_name || pSigner.friendly_name || metadata.friendly_name || rawCustomerName;
    const effectiveEmail = pSigner.email || activeDraft.primary_signer_email || metadata.primary_signer_email || clientRecord.email || '';
    const effectiveTitle = activeDraft.engagement_title || '2026 Tax Services Agreement';

    if (activeHeaderBanner) {
        activeHeaderBanner.style.display = 'block';
        activeHeaderBanner.innerHTML = `
            <div style="background: #eef6fc; border-left: 5px solid #0078d4; border-radius: 4px; padding: 12px 18px; margin-bottom: 20px;">
                <div style="font-size: 18px; font-weight: 700; color: #0078d4; line-height: 1.3;">
                    ${escapeHtml(defaultLegalName)}
                </div>
                <div style="font-size: 14px; font-weight: 600; color: #475569; margin-top: 4px;">
                    📋 Agreement: <span style="color: #1e293b;">${escapeHtml(effectiveTitle)}</span>
                </div>
            </div>
        `;
    }

    let hiddenEngId = document.getElementById('hidden_engagement_id');
    if (!hiddenEngId) {
        hiddenEngId = document.createElement('input');
        hiddenEngId.type = 'hidden';
        hiddenEngId.id = 'hidden_engagement_id';
        hiddenEngId.name = 'engagement_id';
        const form = document.querySelector('form');
        if (form) form.appendChild(hiddenEngId);
    }
    hiddenEngId.value = engId;

    if (isLocked && lockBannerContainer) {
        lockBannerContainer.style.display = 'block';
        lockBannerContainer.innerHTML = `
            <div class="lock-banner-card">
                <div class="lock-banner-title">🔒 Engagement Dispatched (Read-Only Mode)</div>
                <p class="lock-banner-text">
                    Engagement <strong>"${escapeHtml(effectiveTitle)}"</strong> for <strong>${escapeHtml(defaultLegalName)}</strong> was dispatched on <strong>${escapeHtml(lockedMtime)}</strong>. 
                    Workspace parameters are locked to preserve the dispatched contract context.
                </p>
            </div>
        `;
    }

    const isAddressMissing = !addrObj.street || !addrObj.city || !addrObj.state || !addrObj.zip;
    const entityTypeVal = activeDraft.entity_type || metadata.entity_type;
    const isProfileIncomplete = isAddressMissing || !entityTypeVal;

    if (profileContainer) {
        profileContainer.style.display = 'block';
        if (isProfileIncomplete) {
            renderEditableProfilePanel(profileContainer, addrObj, metadata, defaultFriendlyName, defaultLegalName, effectiveEmail, effectiveTitle, activeDraft);
        } else {
            renderReadOnlyProfilePanel(profileContainer, addrObj, metadata, defaultFriendlyName, defaultLegalName, effectiveEmail, effectiveTitle, isLocked, activeDraft);
            injectHiddenMasterContext(
                entityTypeVal, 
                coSigner.name || activeDraft.co_signer_name || metadata.co_signer_name, 
                coSigner.email || activeDraft.co_signer_email || metadata.co_signer_email, 
                addrObj, 
                defaultLegalName, 
                effectiveEmail
            );
        }
    }

    if (syncToolbarContainer) {
        syncToolbarContainer.style.display = 'block';
        const syncCb = document.getElementById('sync_to_qbo');
        if (syncCb) syncCb.disabled = isLocked;
    }

    if (submitBtn) {
        submitBtn.innerText = isLocked ? 'View Dispatched Agreement (Read-Only)' : 'Render PDF Preview';
        submitBtn.style.display = 'block';
    }

    table.style.display = 'table';
    actionsDiv.style.display = isLocked ? 'none' : 'flex';
    if (outOfScopeContainer) outOfScopeContainer.style.display = 'block';

    const dateSelect = document.getElementById('estimate-date-option');
    if (dateSelect) {
        if (activeDraft.estimate_date_option) dateSelect.value = activeDraft.estimate_date_option;
        dateSelect.disabled = isLocked;
    }

    const fieldMapping = {
        'friendly_name': defaultFriendlyName,
        'legal_name': defaultLegalName,
        'primary_signer_email': effectiveEmail,
        'co_signer_name': coSigner.name || activeDraft.co_signer_name || metadata.co_signer_name || '',
        'co_signer_email': coSigner.email || activeDraft.co_signer_email || metadata.co_signer_email || '',
        'street': addrObj.street || '',
        'city': addrObj.city || '',
        'state': addrObj.state || '',
        'zip': addrObj.zip || '',
        'engagement_title': effectiveTitle
    };

    Object.keys(fieldMapping).forEach(fieldName => {
        const input = document.querySelector(`input[name="${fieldName}"]`);
        if (input && fieldMapping[fieldName]) input.value = fieldMapping[fieldName];
    });

    const hEntity = document.querySelector('select[name="entity_type"]');
    if (hEntity && entityTypeVal) hEntity.value = entityTypeVal;

    if (isLocked && profileContainer) {
        profileContainer.querySelectorAll('input, select, button').forEach(el => el.disabled = true);
    }

    if (window.reconstructedRows && window.reconstructedRows.length > 0) {
        window.reconstructedRows.forEach(row => addServiceRow(row, isLocked));
    } else if (draftData.rows && draftData.rows.length > 0) {
        draftData.rows.forEach(row => addServiceRow(row, isLocked));
    } else {
        addServiceRow(null, isLocked);
    }

    const oosToPass = (activeDraft.out_of_scope_items !== undefined) 
        ? activeDraft.out_of_scope_items 
        : draftData.out_of_scope_items;

    rehydrateOutOfScopeItems(oosToPass, isLocked);

    const customOosInput = document.getElementById('new-out-of-scope-input');
    const customOosBtn = document.querySelector('.add-out-of-scope-row button');
    if (customOosInput) customOosInput.disabled = isLocked;
    if (customOosBtn) customOosBtn.disabled = isLocked;
}

function renderEditableProfilePanel(container, addr, meta, defaultFriendlyName, defaultLegalName, clientEmail, engagementTitle = '2026 Tax Services Agreement', draftData = {}) {
    const coSigner = draftData.co_signer || {};
    const coSignerEmailVal = coSigner.email || draftData.co_signer_email || meta.co_signer_email || '';
    const coSignerNameVal = coSigner.name || draftData.co_signer_name || meta.co_signer_name || '';
    const entityTypeVal = draftData.entity_type || meta.entity_type || 'individual';

    container.innerHTML = `
        <div class="profile-card profile-card-incomplete">
            <div class="profile-card-title">⚠️ Missing Required Account Settings</div>
            <p style="margin: 0 0 15px 0; font-size: 13px; color: #666;">
                This customer profile is missing vital parameters in QuickBooks Online. Please enter the details below. 
                Submitting this form will update customer metadata in Notes upon Estimate generation.
            </p>

            <input type="hidden" name="profile_verified" value="true">
            
            <div class="profile-editable-grid-top">
                <div class="form-field-group engagement-title-group">
                    <label class="field-label">Engagement Title</label>
                    <input type="text" name="engagement_title" value="${escapeHtml(engagementTitle)}" required placeholder="e.g., 2026 Tax Services Agreement, Q3 Advisory Addendum...">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Client Name (QBO/SharePoint)</label>
                    <input type="text" name="legal_name" value="${escapeHtml(defaultLegalName)}" required placeholder="e.g., Susan Smith LLC">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Signature Name</label>
                    <input type="text" name="friendly_name" value="${escapeHtml(defaultFriendlyName)}" required placeholder="e.g., Susan Smith">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Engagement Email</label>
                    <input type="email" name="primary_signer_email" value="${escapeHtml(clientEmail || '')}" required placeholder="client@example.com">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Account Classification</label>
                    <select name="entity_type" id="heal_entity_type" onchange="onProfileEntityChange()" required>
                        <option value="">-- Choose Classification --</option>
                        <option value="individual" ${entityTypeVal === 'individual' ? 'selected' : ''}>Individual (Form 1040)</option>
                        <option value="sm_llc" ${entityTypeVal === 'sm_llc' ? 'selected' : ''}>Single Member LLC (Schedule C)</option>
                        <option value="s_corp" ${entityTypeVal === 's_corp' ? 'selected' : ''}>S-Corporation (Form 1120S)</option>
                        <option value="partnership" ${entityTypeVal === 'partnership' ? 'selected' : ''}>Partnership (Form 1065)</option>
                        <option value="c_corp" ${entityTypeVal === 'c_corp' ? 'selected' : ''}>C-Corporation (Form 1120)</option>
                        <option value="non_profit" ${entityTypeVal === 'non_profit' ? 'selected' : ''}>Tax-Exempt Org (Form 990)</option>
                        <option value="trust" ${entityTypeVal === 'trust' ? 'selected' : ''}>Trust / Estate (Form 1041)</option>
                    </select>
                </div>
            </div>

            <div class="profile-editable-grid-middle">
                <div class="form-field-group">
                    <label class="field-label">Street Address</label>
                    <input type="text" name="street" value="${escapeHtml(addr.street || '')}" required placeholder="e.g., 123 Main St">
                </div>
                <div class="form-field-group">
                    <label class="field-label">City</label>
                    <input type="text" name="city" value="${escapeHtml(addr.city || '')}" required placeholder="e.g., Fort Worth">
                </div>
                <div class="form-field-group">
                    <label class="field-label">State</label>
                    <input type="text" name="state" value="${escapeHtml(addr.state || '')}" required placeholder="TX" maxlength="2">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Zip Code</label>
                    <input type="text" name="zip" value="${escapeHtml(addr.zip || '')}" required placeholder="76102">
                </div>
            </div>

            <div class="profile-editable-grid-bottom">
                <div class="form-field-group">
                    <label class="field-label">Additional Signer Full Name</label>
                    <input type="text" name="co_signer_name" value="${escapeHtml(coSignerNameVal)}" placeholder="e.g., Jane Doe">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Additional Signer Email</label>
                    <input type="email" name="co_signer_email" value="${escapeHtml(coSignerEmailVal)}" placeholder="spouse@example.com">
                </div>
            </div>
        </div>
    `;
}

function renderReadOnlyProfilePanel(container, addr, meta, defaultFriendlyName, defaultLegalName, clientEmail, engagementTitle = '2026 Tax Services Agreement', isLocked = false, draftData = {}) {
    const formattedAddress = `${addr.street || ''}, ${addr.city || ''}, ${addr.state || ''} ${addr.zip || ''}`;
    const entityTypeVal = draftData.entity_type || meta.entity_type || 'individual';
    const displayClassification = ENTITY_DISPLAY_NAMES[entityTypeVal] || entityTypeVal || 'Individual';
    const isOrg = ORGANIZATION_ENTITY_TYPES.includes(entityTypeVal);
    
    const coSigner = draftData.co_signer || {};
    const coSignerEmailVal = (coSigner.email || draftData.co_signer_email || meta.co_signer_email || '').trim();
    const coSignerNameVal = (coSigner.name || draftData.co_signer_name || meta.co_signer_name || '').trim();
    const isDualSigner = (coSignerEmailVal.includes('@') || coSignerNameVal.length > 0);
    
    let signatureGridDisplay = 'Single Signer';
    if (isDualSigner) {
        if (coSignerNameVal && coSignerEmailVal) {
            signatureGridDisplay = `Dual Signer: ${escapeHtml(coSignerNameVal)} (${escapeHtml(coSignerEmailVal)})`;
        } else if (coSignerNameVal) {
            signatureGridDisplay = `Dual Signer: ${escapeHtml(coSignerNameVal)}`;
        } else {
            signatureGridDisplay = `Dual Signer: ${escapeHtml(coSignerEmailVal)}`;
        }
    }
    
    const readonlyAttr = 'readonly tabindex="-1"';
    const disabledAttr = isLocked ? 'disabled' : '';

    container.innerHTML = `
        <div class="profile-card profile-card-complete">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div class="profile-card-title" style="color: #107c41; margin-bottom: 0;">✔ Customer Profile Verified</div>
                ${isLocked ? '' : '<button type="button" class="btn-add-row btn-edit-profile" onclick="toggleProfileEditMode()" style="font-size: 12px; padding: 4px 10px;">✏️ Edit Profile Parameters</button>'}
            </div>
            
            <div class="profile-editable-grid-top" style="margin-bottom: 12px;">
                <div class="form-field-group engagement-title-group">
                    <label class="field-label">Engagement Title</label>
                    <input type="text" name="engagement_title" value="${escapeHtml(unescapeHtml(engagementTitle))}" ${disabledAttr} required placeholder="e.g., 2026 Tax Services Agreement, Q3 Advisory Addendum...">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Client Name (QBO/SharePoint)</label>
                    <input type="text" name="legal_name" class="read-only-input" value="${escapeHtml(unescapeHtml(defaultLegalName))}" ${readonlyAttr}>
                </div>
                <div class="form-field-group">
                    <label class="field-label">Signature Name</label>
                    <input type="text" name="friendly_name" class="read-only-input" value="${escapeHtml(unescapeHtml(defaultFriendlyName))}" ${readonlyAttr}>
                </div>
                <div class="form-field-group">
                    <label class="field-label">Engagement Email</label>
                    <input type="email" name="primary_signer_email" class="read-only-input" value="${escapeHtml(clientEmail || '')}" ${readonlyAttr}>
                </div>
                <div class="form-field-group">
                    <label class="field-label">Account Classification</label>
                    <div style="padding-top: 6px;">
                        <span class="badge ${isOrg ? 'badge-organization' : 'badge-individual'}">${escapeHtml(displayClassification)}</span>
                    </div>
                </div>
            </div>

            <div class="verified-bottom-grid">
                <div>
                    <strong style="font-size: 12px; color: #4a5568;">Billing Address:</strong><br>
                    <span style="color:#555; font-size: 13px;">${escapeHtml(formattedAddress)}</span>
                </div>
                <div>
                    <strong style="font-size: 12px; color: #4a5568;">Signature Grid:</strong><br>
                    <span style="color:#555; font-size: 13px;">${signatureGridDisplay}</span>
                </div>
            </div>

            <p style="margin: 12px 0 0 0; font-size: 11px; color: #888; font-style: italic;">
                Modifying parameters above updates draft state and saves JSON signature metadata back to QBO Notes upon Estimate generation.
            </p>
        </div>
    `;
}

function toggleProfileEditMode() {
    const hiddenSelect = document.getElementById('client-select');
    const selectedVal = hiddenSelect ? hiddenSelect.value : '';
    const container = document.getElementById('profile-healing-container');
    if (!selectedVal || !container) return;

    const parts = selectedVal.split(':');
    const qboId = parts[0];
    const engId = parts.length > 1 ? parts[1] : '0';

    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    if (!clientKey || !window.clientData[clientKey]) return;

    const record = window.clientData[clientKey];
    const draft = (record.engagements && record.engagements[engId]) ? record.engagements[engId] : {};
    const meta = record.metadata || {};

    const rawCustomerName = clientKey.split(/\s*\(Customer/)[0].trim();

    const friendlyInput = document.querySelector('input[name="friendly_name"]');
    const legalInput = document.querySelector('input[name="legal_name"]');
    const emailInput = document.querySelector('input[name="primary_signer_email"]');
    const titleInput = document.querySelector('input[name="engagement_title"]');

    const pSigner = draft.primary_signer || {};

    const defaultFriendlyName = friendlyInput ? friendlyInput.value : (pSigner.friendly_name || draft.friendly_name || meta.friendly_name || rawCustomerName);
    const defaultLegalName = legalInput ? legalInput.value : (pSigner.legal_name || draft.legal_name || rawCustomerName);
    const defaultEmail = emailInput ? emailInput.value : (pSigner.email || draft.primary_signer_email || meta.primary_signer_email || record.email || '');
    const defaultTitle = titleInput ? titleInput.value : (draft.engagement_title || '2026 Tax Services Agreement');

    renderEditableProfilePanel(
        container, 
        draft.billing_address || record.address || {}, 
        meta, 
        defaultFriendlyName, 
        defaultLegalName, 
        defaultEmail, 
        defaultTitle, 
        draft
    );
    
    const verifiedFlagInput = container.querySelector('input[name="profile_verified"]');
    if (verifiedFlagInput) verifiedFlagInput.value = "true";
}

function onProfileEntityChange() {
    const hiddenSelect = document.getElementById('client-select');
    const selectedVal = hiddenSelect ? hiddenSelect.value : '';
    if (!selectedVal) return;

    const parts = selectedVal.split(':');
    const qboId = parts[0];
    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    if (!clientKey || !window.clientData[clientKey]) return;

    const exposedServices = window.clientData[clientKey].exposed_services || [];
    const healEntitySelect = document.getElementById('heal_entity_type');
    const currentRawEntity = healEntitySelect ? healEntitySelect.value.toLowerCase() : '';

    if (currentRawEntity) {
        window.clientData[clientKey].metadata = window.clientData[clientKey].metadata || {};
        window.clientData[clientKey].metadata.entity_type = currentRawEntity;
    }

    const currentContextType = ORGANIZATION_ENTITY_TYPES.includes(currentRawEntity) ? 'organization' : 'individual';

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

function addServiceRow(rowData = null, isLocked = false) {
    const tbody = document.getElementById('service-tbody');
    const hiddenSelect = document.getElementById('client-select');
    const selectedVal = hiddenSelect ? hiddenSelect.value : '';

    if (!selectedVal) return;

    const parts = selectedVal.split(':');
    const qboId = parts[0];
    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    if (!clientKey || !window.clientData[clientKey]) return;

    const exposedServices = window.clientData[clientKey].exposed_services || [];
    let currentRawEntity = '';
    const healEntitySelect = document.getElementById('heal_entity_type');
    
    if (healEntitySelect && healEntitySelect.value) {
        currentRawEntity = healEntitySelect.value.toLowerCase();
    } else if (window.clientData[clientKey].metadata && window.clientData[clientKey].metadata.entity_type) {
        currentRawEntity = window.clientData[clientKey].metadata.entity_type.toLowerCase();
    }

    const currentContextType = ORGANIZATION_ENTITY_TYPES.includes(currentRawEntity) ? 'organization' : 'individual';

    rowCounter++;
    const currentId = rowCounter;
    const tr = document.createElement('tr');
    tr.id = `row_container_${currentId}`;

    let targetService = rowData ? (rowData.service || '') : '';
    targetService = unescapeHtml(targetService);

    const feeValue = rowData ? Math.round(parseFloat(rowData.fee || 0)) : '0';
    const notesValue = rowData ? (rowData.notes || '') : '';
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
            <input type="hidden" id="row_service_${currentId}" name="row_service_${currentId}" value="${escapeHtml(targetService)}">
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

function removeServiceRow(id) {
    const tr = document.getElementById(`row_container_${id}`);
    if (tr) tr.remove();
    calculateGridTotals();
}

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

    if (svcNameInput) svcNameInput.value = itemName;

    let resolvedType = rawType;
    const hiddenSelect = document.getElementById('client-select');
    const selectedVal = hiddenSelect ? hiddenSelect.value : '';

    if (['both', 'individual', 'organization'].includes(rawType.toLowerCase())) {
        const healEntitySelect = document.getElementById('heal_entity_type');
        let currentRawEntity = 'individual';
        if (healEntitySelect && healEntitySelect.value) {
            currentRawEntity = healEntitySelect.value.toLowerCase();
        } else if (selectedVal) {
            const parts = selectedVal.split(':');
            const qboId = parts[0];
            const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
            if (clientKey && window.clientData[clientKey]) {
                const meta = window.clientData[clientKey].metadata || {};
                currentRawEntity = (meta.entity_type || 'individual').toLowerCase();
            }
        }
        resolvedType = ORGANIZATION_ENTITY_TYPES.includes(currentRawEntity) ? 'organization' : 'individual';
    }

    if (bpInput) bpInput.value = resolvedType;

    if (badgeContainer) {
        const isOrganization = (resolvedType.toLowerCase() === 'organization');
        badgeContainer.innerHTML = `<span class="badge ${isOrganization ? 'badge-organization' : 'badge-individual'}">${escapeHtml(resolvedType)}</span>`;
    }

    if (!bypassDefaultNotes) {
        const defaultFee = selectedOption.getAttribute('data-fee') || '0';
        if (feeInput) feeInput.value = (defaultFee !== undefined && defaultFee !== null && defaultFee !== '') ? defaultFee : '0';

        if (notesTextarea && selectedVal) {
            const parts = selectedVal.split(':');
            const qboId = parts[0];
            const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
            if (clientKey && window.clientData[clientKey]) {
                const exposedServices = window.clientData[clientKey].exposed_services || [];
                const serviceMatch = exposedServices.find(svc => svc.name === itemName);
                notesTextarea.value = serviceMatch ? (serviceMatch.notes || '') : '';
            }
        }
    }

    calculateGridTotals();
}

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

    if (discountNode) discountNode.innerText = discountAmount > 0 ? `-$${Math.round(discountAmount).toLocaleString()}` : `$0`;
    if (balanceNode) balanceNode.innerText = `$${Math.round(totalNet).toLocaleString()}`;
}

/* Batch Orchestrator Functions */
let activeModalTargetKey = null;

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

function renderBatchTableGrid() {
    const tbody = document.getElementById('batch-tbody');
    if (!tbody || !window.clientData) return;

    const currentSelections = {};
    document.querySelectorAll('.batch-checkbox').forEach(cb => {
        const qId = cb.getAttribute('data-qbo-id');
        const eId = cb.getAttribute('data-eng-id');
        if (qId && eId) {
            currentSelections[`${qId}:${eId}`] = cb.checked;
        }
    });

    tbody.innerHTML = '';

    Object.keys(window.clientData).forEach(clientKey => {
        const client = window.clientData[clientKey];
        const qboId = client.id;
        const meta = client.metadata || {};
        const clientAddr = client.address || {};

        const engagements = client.engagements || {};
        Object.keys(engagements).forEach(engId => {
            const draft = engagements[engId];
            const isLocked = Boolean(draft.is_locked);
            const engTitle = draft.engagement_title || `Engagement (${engId})`;

            const rawFormat = (draft.delivery_format || 'electronic').toLowerCase();
            const isPaper = rawFormat.includes('paper');
            
            let clientFee = 0.0;
            if (draft.rows && draft.rows.length > 0) {
                draft.rows.forEach(r => { clientFee += parseFloat(r.fee || 0); });
            }

            const pSigner = draft.primary_signer || {};
            const coSigner = draft.co_signer || {};
            const addrObj = draft.billing_address || clientAddr;

            const street = addrObj.street || '';
            const city = addrObj.city || '';
            const entityType = draft.entity_type || meta.entity_type;
            const email = pSigner.email || draft.primary_signer_email || client.email;

            const hasServiceRows = Boolean(draft.rows && Array.isArray(draft.rows) && draft.rows.length > 0);
            const isAddressMissing = !street || !city;
            const isConfigMissing = !entityType;
            const isEmailMissing = !email;

            const isDataIncomplete = !hasServiceRows || isAddressMissing || isConfigMissing || isEmailMissing;

            let statusBadge = '<span class="badge badge-electronic">Ready</span>';
            let checkboxDisabled = '';

            if (isLocked) {
                statusBadge = '<span class="badge badge-locked">🔒 Sent</span>';
                checkboxDisabled = 'disabled';
            } else if (isDataIncomplete) {
                statusBadge = '<span class="badge badge-warning">⚠️ Data Incomplete</span>';
                checkboxDisabled = 'disabled';
            }

            const selectionKey = `${qboId}:${engId}`;
            let isChecked = false;
            if (Object.prototype.hasOwnProperty.call(currentSelections, selectionKey)) {
                isChecked = currentSelections[selectionKey];
            } else {
                isChecked = (!isLocked && !isDataIncomplete);
            }

            const checkedAttr = isChecked ? 'checked' : '';

            const formatBadgeClass = isPaper ? 'badge-paper' : 'badge-electronic';
            const formatText = isPaper ? 'Paper' : 'Electronic';
            const disabledCursor = isLocked ? 'cursor: default;' : 'cursor: pointer;';
            
            const formatBadgeHtml = `
                <span class="badge ${formatBadgeClass}" 
                      onclick="${isLocked ? '' : `toggleClientDeliveryFormat('${qboId}', '${engId}')`}" 
                      title="${isLocked ? 'Locked' : 'Click to toggle delivery format'}" 
                      style="${disabledCursor} user-select: none;">
                    ${formatText} 🔄
                </span>
            `;

            const coSignerEmailVal = coSigner.email || draft.co_signer_email || meta.co_signer_email || '';
            const coSignerNameVal = coSigner.name || draft.co_signer_name || meta.co_signer_name || '';
            const isDualSigner = (coSignerEmailVal.includes('@') || coSignerNameVal.length > 0);

            const tr = document.createElement('tr');
            tr.id = `batch_row_${qboId}_${engId}`;
            tr.className = `batch-row-item format-${isPaper ? 'paper' : 'electronic'}`;
            tr.innerHTML = `
                <td style="text-align: center;">
                    <input type="checkbox" class="batch-checkbox" data-qbo-id="${qboId}" data-eng-id="${engId}" ${checkboxDisabled} ${checkedAttr} onchange="updateBatchSummaryMetrics()">
                </td>
                <td style="font-family: monospace; font-size: 12px; color: #555;">${qboId}</td>
                <td>
                    <strong>${escapeHtml(pSigner.friendly_name || draft.friendly_name || meta.friendly_name || clientKey.split(' (Customer')[0])}</strong>
                    <br/><small style="color: #0078d4; font-weight: 600;">${escapeHtml(engTitle)}</small>
                </td>
                <td><span class="badge ${entityType === 'individual' ? 'badge-individual' : 'badge-organization'}">${escapeHtml(entityType || 'individual')}</span></td>
                <td style="font-size: 12px; color: #444;">${isDualSigner ? 'Joint (' + escapeHtml(coSignerNameVal || coSignerEmailVal) + ')' : 'Single'}</td>
                <td style="text-align: right; font-family: monospace; font-weight: bold; font-size: 14px;">$${Math.round(clientFee).toLocaleString()}</td>
                <td>${formatBadgeHtml}</td>
                <td>${statusBadge}</td>
                <td style="text-align: center;">
                    <button type="button" class="btn-add-row" onclick="openBatchEditModal('${qboId}', '${engId}')" style="padding: 4px 10px; font-size: 12px;">✏️ Edit</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    });

    updateBatchSummaryMetrics();
}

async function toggleClientDeliveryFormat(qboId, engId) {
    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    if (!clientKey) return;

    const client = window.clientData[clientKey];
    if (!client.engagements || !client.engagements[engId]) return;

    const draft = client.engagements[engId];
    const currentFmt = (draft.delivery_format || 'electronic').toLowerCase();
    const newFmt = currentFmt.includes('paper') ? 'electronic' : 'paper';

    draft.delivery_format = newFmt;
    renderBatchTableGrid();

    const pSigner = draft.primary_signer || {};
    const coSigner = draft.co_signer || {};

    const syncQboCb = document.getElementById('sync_to_qbo');
    const syncQboVal = syncQboCb ? (syncQboCb.checked ? 'true' : 'false') : 'true';

    const urlParams = new URLSearchParams();
    urlParams.append('action', 'save_draft_only');
    urlParams.append('ajax', 'true');
    urlParams.append('client_name', clientKey);
    urlParams.append('engagement_id', engId);
    urlParams.append('engagement_title', draft.engagement_title || '2026 Tax Services Agreement');
    urlParams.append('delivery_format', newFmt);
    urlParams.append('sync_to_qbo', syncQboVal);

    urlParams.append('friendly_name', draft.friendly_name || pSigner.friendly_name || client.metadata.friendly_name || '');
    urlParams.append('legal_name', pSigner.legal_name || draft.legal_name || '');
    urlParams.append('primary_signer_email', pSigner.email || draft.primary_signer_email || client.metadata.primary_signer_email || client.email || '');
    urlParams.append('entity_type', draft.entity_type || 'individual');
    urlParams.append('co_signer_name', coSigner.name || draft.co_signer_name || client.metadata.co_signer_name || '');
    urlParams.append('co_signer_email', coSigner.email || draft.co_signer_email || client.metadata.co_signer_email || '');

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

    urlParams.append('oos_submitted', 'true');
    if (draft.out_of_scope_items && typeof draft.out_of_scope_items === 'object') {
        Object.entries(draft.out_of_scope_items).forEach(([k, v]) => {
            urlParams.append(k, v);
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

function updateBatchSummaryMetrics() {
    const checkedBoxes = document.querySelectorAll('.batch-checkbox:checked');
    let totalFee = 0.0;
    let electronicCount = 0;
    let paperCount = 0;

    checkedBoxes.forEach(cb => {
        const qboId = cb.getAttribute('data-qbo-id');
        const engId = cb.getAttribute('data-eng-id');
        
        const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
        if (clientKey) {
            const client = window.clientData[clientKey];
            const draft = (client.engagements && client.engagements[engId]) ? client.engagements[engId] : {};
            const isPaper = (draft.delivery_format || 'electronic').toLowerCase().includes('paper');
            
            if (isPaper) paperCount++; else electronicCount++;

            if (draft.rows) {
                draft.rows.forEach(r => { totalFee += parseFloat(r.fee || 0); });
            }
        }
    });

    const summaryNode = document.getElementById('batch-summary-bar');
    if (summaryNode) {
        summaryNode.innerHTML = `
            <strong>Selected:</strong> ${checkedBoxes.length} engagement(s) &nbsp;|&nbsp;
            <strong>Electronic:</strong> ${electronicCount} &nbsp;|&nbsp;
            <strong>Paper:</strong> ${paperCount} &nbsp;|&nbsp;
            <strong>Batch Total:</strong> $${Math.round(totalFee).toLocaleString()}
        `;
    }
}

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

function selectAllBatchRows(shouldSelect) {
    document.querySelectorAll('.batch-checkbox:not([disabled])').forEach(cb => {
        cb.checked = shouldSelect;
    });
    updateBatchSummaryMetrics();
}

function openBatchEditModal(qboId, engId) {
    activeModalTargetKey = `${qboId}:${engId}`;
    
    const hiddenSelect = document.getElementById('client-select');
    const textInput = document.getElementById('client-select-input');
    const datalist = document.getElementById('client-select-options');

    const targetVal = `${qboId}:${engId}`;

    if (hiddenSelect) hiddenSelect.value = targetVal;

    if (textInput && datalist) {
        for (let i = 0; i < datalist.options.length; i++) {
            if (datalist.options[i].getAttribute('data-value') === targetVal) {
                textInput.value = datalist.options[i].value;
                break;
            }
        }
    }

    onClientChange();

    const modal = document.getElementById('batch-edit-modal');
    const modalContentContainer = document.getElementById('modal-workspace-container');

    modalContentContainer.appendChild(document.getElementById('profile-healing-container'));
    modalContentContainer.appendChild(document.getElementById('qbo-sync-toolbar-container'));
    modalContentContainer.appendChild(document.getElementById('service-table'));
    modalContentContainer.appendChild(document.getElementById('actions-container'));
    modalContentContainer.appendChild(document.getElementById('out-of-scope-container'));

    const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
    const clientName = clientKey ? clientKey.split(' (Customer')[0] : qboId;

    document.getElementById('modal-client-title').innerText = `Edit Engagement — ${clientName}`;
    modal.style.display = 'flex';
}

function returnElementsToSingleWorkspace() {
    const singleForm = document.querySelector('#single-client-workspace form');
    if (singleForm) {
        const profileContainer = document.getElementById('profile-healing-container');
        const syncToolbarContainer = document.getElementById('qbo-sync-toolbar-container');
        const serviceTable = document.getElementById('service-table');
        const actionsContainer = document.getElementById('actions-container');
        const oosContainer = document.getElementById('out-of-scope-container');
        const submitContainer = singleForm.querySelector('.submit-container');

        if (submitContainer) {
            singleForm.insertBefore(profileContainer, submitContainer);
            if (syncToolbarContainer) singleForm.insertBefore(syncToolbarContainer, submitContainer);
            singleForm.insertBefore(serviceTable, submitContainer);
            singleForm.insertBefore(actionsContainer, submitContainer);
            singleForm.insertBefore(oosContainer, submitContainer);
        } else {
            singleForm.appendChild(profileContainer);
            if (syncToolbarContainer) singleForm.appendChild(syncToolbarContainer);
            singleForm.appendChild(serviceTable);
            singleForm.appendChild(actionsContainer);
            singleForm.appendChild(oosContainer);
        }
    }
}

function cancelBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    if (!modal) return;

    returnElementsToSingleWorkspace();

    modal.style.display = 'none';
    activeModalTargetKey = null;
    
    renderBatchTableGrid();
}

async function closeBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    const hiddenSelect = document.getElementById('client-select');
    const selectedVal = hiddenSelect ? hiddenSelect.value : '';

    if (selectedVal) {
        const parts = selectedVal.split(':');
        const qboId = parts[0];
        const engId = parts.length > 1 ? parts[1] : '0';

        const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));

        if (clientKey && window.clientData[clientKey]) {
            const syncQboCb = document.getElementById('sync_to_qbo');
            const syncQboVal = syncQboCb ? (syncQboCb.checked ? 'true' : 'false') : 'true';

            const urlParams = new URLSearchParams();
            urlParams.append('action', 'save_draft_only');
            urlParams.append('ajax', 'true');
            urlParams.append('client_name', clientKey);
            urlParams.append('engagement_id', engId);
            urlParams.append('sync_to_qbo', syncQboVal);

            const engTitleInput = document.querySelector('input[name="engagement_title"]');
            if (engTitleInput) urlParams.append('engagement_title', engTitleInput.value);

            const estDateSelect = document.getElementById('estimate-date-option');
            if (estDateSelect) urlParams.append('estimate_date_option', estDateSelect.value);

            const friendlyInput = document.querySelector('input[name="friendly_name"]');
            const legalInput = document.querySelector('input[name="legal_name"]');
            const emailInput = document.querySelector('input[name="primary_signer_email"]');
            const entitySelect = document.querySelector('select[name="entity_type"]');
            const coSignerEmailInput = document.querySelector('input[name="co_signer_email"]');
            const coSignerNameInput = document.querySelector('input[name="co_signer_name"]');
            const streetInput = document.querySelector('input[name="street"]');
            const cityInput = document.querySelector('input[name="city"]');
            const stateInput = document.querySelector('input[name="state"]');
            const zipInput = document.querySelector('input[name="zip"]');
            const verifiedFlagInput = document.querySelector('input[name="profile_verified"]');

            if (friendlyInput) urlParams.append('friendly_name', friendlyInput.value);
            if (legalInput) urlParams.append('legal_name', legalInput.value);
            if (emailInput) urlParams.append('primary_signer_email', emailInput.value);
            if (entitySelect) urlParams.append('entity_type', entitySelect.value);
            if (coSignerEmailInput) urlParams.append('co_signer_email', coSignerEmailInput.value);
            if (coSignerNameInput) urlParams.append('co_signer_name', coSignerNameInput.value);
            if (streetInput) urlParams.append('street', streetInput.value);
            if (cityInput) urlParams.append('city', cityInput.value);
            if (stateInput) urlParams.append('state', stateInput.value);
            if (zipInput) urlParams.append('zip', zipInput.value);
            if (verifiedFlagInput) urlParams.append('profile_verified', verifiedFlagInput.value);

            const activeClientObj = window.clientData[clientKey];
            const currentEngObj = (activeClientObj.engagements && activeClientObj.engagements[engId]) ? activeClientObj.engagements[engId] : {};
            urlParams.append('delivery_format', currentEngObj.delivery_format || 'electronic');

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

            urlParams.append('oos_submitted', 'true');
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
                        const assignedEngId = resData.engagement_id || engId;
                        activeClientObj.engagements = activeClientObj.engagements || {};
                        activeClientObj.engagements[assignedEngId] = resData.draft;
                    }
                }
            } catch (err) {
                console.error("Failed to execute background draft save:", err);
            }
        }
    }

    const savedTargetKey = activeModalTargetKey;

    returnElementsToSingleWorkspace();

    modal.style.display = 'none';
    activeModalTargetKey = null;
    
    renderBatchTableGrid();

    if (savedTargetKey) {
        const parts = savedTargetKey.split(':');
        const editedCb = document.querySelector(`.batch-checkbox[data-qbo-id="${parts[0]}"][data-eng-id="${parts[1]}"]`);
        if (editedCb && !editedCb.disabled) {
            editedCb.checked = true;
            updateBatchSummaryMetrics();
        }
    }
}

async function executeBatchPipelineSubmission() {
    const selectedCheckboxes = document.querySelectorAll('.batch-checkbox:checked');
    if (selectedCheckboxes.length === 0) {
        alert("Please select at least one engagement to process.");
        return;
    }

    if (!confirm(`Are you sure you want to process and dispatch ${selectedCheckboxes.length} client engagement(s)?`)) return;

    const progressOverlay = document.getElementById('batch-progress-overlay');
    const progressBar = document.getElementById('batch-progress-fill');
    const terminalLog = document.getElementById('batch-terminal-log');
    const doneBtn = document.getElementById('btn-close-progress');

    progressOverlay.style.display = 'flex';
    doneBtn.style.display = 'none';
    terminalLog.innerHTML = `Starting batch process for ${selectedCheckboxes.length} engagement(s)...\n`;

    let completed = 0;

    for (const cb of selectedCheckboxes) {
        const qboId = cb.getAttribute('data-qbo-id');
        const engId = cb.getAttribute('data-eng-id');

        const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
        if (!clientKey) continue;

        const client = window.clientData[clientKey];
        const draft = (client.engagements && client.engagements[engId]) ? client.engagements[engId] : {};
        
        const isPaper = (draft.delivery_format || 'electronic').toLowerCase().includes('paper');
        const targetAction = isPaper ? 'execute_transactional_pipeline_paper' : 'execute_transactional_pipeline';

        terminalLog.innerHTML += `\n[${completed + 1}/${selectedCheckboxes.length}] Processing QBO ID ${qboId} / Eng ${engId} (${isPaper ? 'PAPER' : 'E-SIGN'})... `;

        const pSigner = draft.primary_signer || {};
        const coSigner = draft.co_signer || {};

        const syncQboCb = document.getElementById('sync_to_qbo');
        const syncQboVal = syncQboCb ? (syncQboCb.checked ? 'true' : 'false') : 'true';

        const urlParams = new URLSearchParams();
        urlParams.append('action', targetAction);
        urlParams.append('ajax', 'true');
        urlParams.append('client_name', clientKey);
        urlParams.append('engagement_id', engId);
        urlParams.append('engagement_title', draft.engagement_title || '2026 Tax Services Agreement');
        urlParams.append('delivery_method', isPaper ? 'paper' : '');
        urlParams.append('sync_to_qbo', syncQboVal);

        urlParams.append('friendly_name', pSigner.friendly_name || draft.friendly_name || client.metadata.friendly_name || '');
        urlParams.append('legal_name', pSigner.legal_name || draft.legal_name || '');
        urlParams.append('primary_signer_email', pSigner.email || draft.primary_signer_email || client.metadata.primary_signer_email || client.email || '');
        urlParams.append('entity_type', draft.entity_type || 'individual');
        urlParams.append('co_signer_name', coSigner.name || draft.co_signer_name || client.metadata.co_signer_name || '');
        urlParams.append('co_signer_email', coSigner.email || draft.co_signer_email || client.metadata.co_signer_email || '');

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

        urlParams.append('oos_submitted', 'true');
        if (draft.out_of_scope_items && typeof draft.out_of_scope_items === 'object') {
            Object.entries(draft.out_of_scope_items).forEach(([k, v]) => {
                urlParams.append(k, v);
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
                    terminalLog.innerHTML += `SUCCESS ✔ (Estimate #${resData.estimate_id})`;
                } else {
                    terminalLog.innerHTML += `FAILED ❌ (${resData.message || 'Unknown error'})`;
                }
            } else {
                let errorDetails = `HTTP ${resp.status}`;
                try {
                    const errData = await resp.json();
                    if (errData.message) errorDetails = errData.message;
                } catch (e) {
                }
                terminalLog.innerHTML += `FAILED ❌ (${errorDetails})`;
            }
        } catch (err) {
            terminalLog.innerHTML += `ERROR ❌ (${err.message})`;
        }

        completed++;
        progressBar.style.width = `${(completed / selectedCheckboxes.length) * 100}%`;
        terminalLog.scrollTop = terminalLog.scrollHeight;

        if (completed < selectedCheckboxes.length && BATCH_THROTTLE_DELAY_MS > 0) {
            await sleep(BATCH_THROTTLE_DELAY_MS);
        }
    }

    terminalLog.innerHTML += `\n\n========================================\nScope clone execution complete!`;
    doneBtn.style.display = 'inline-block';
}

document.addEventListener('DOMContentLoaded', () => {
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
            if (action === 'revert_to_workspace' || action === 'save_draft_only' || action === 'send_m365_email') return true;

            const hiddenSelect = document.getElementById('client-select');
            if (!hiddenSelect || !hiddenSelect.value) return true;

            const parts = hiddenSelect.value.split(':');
            const qboId = parts[0];
            const engId = parts.length > 1 ? parts[1] : '0';

            const clientKey = Object.keys(window.clientData || {}).find(k => String(window.clientData[k].id) === String(qboId));
            if (clientKey && window.clientData[clientKey]) {
                const clientRecord = window.clientData[clientKey];
                if (clientRecord.engagements && clientRecord.engagements[engId] && clientRecord.engagements[engId].is_locked) {
                    return true;
                }
            }

            const primaryEmailInput = document.querySelector('input[name="primary_signer_email"]');
            if (primaryEmailInput && primaryEmailInput.value.trim() !== "") {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (!emailRegex.test(primaryEmailInput.value.trim())) {
                    alert("Please enter a valid primary engagement email address.");
                    e.preventDefault();
                    return false;
                }
            }

            const coSignerEmailInput = document.querySelector('input[name="co_signer_email"]');
            const coSignerNameInput = document.querySelector('input[name="co_signer_name"]');

            const CLEAR_KEYWORDS = ["none", "null", "single", "n/a"];
            const hasEmail = coSignerEmailInput && coSignerEmailInput.value.trim() !== "" && !CLEAR_KEYWORDS.includes(coSignerEmailInput.value.trim().toLowerCase());
            const hasName = coSignerNameInput && coSignerNameInput.value.trim() !== "" && !CLEAR_KEYWORDS.includes(coSignerNameInput.value.trim().toLowerCase());

            if (hasEmail || hasName) {
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
                if (hasEmail && !emailRegex.test(coSignerEmailInput.value.trim())) {
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

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && activeModalTargetKey) {
            cancelBatchEditModal();
        }
    });

    window.addEventListener('click', (e) => {
        const modal = document.getElementById('batch-edit-modal');
        if (e.target === modal && activeModalTargetKey) {
            cancelBatchEditModal();
        }
    });
});