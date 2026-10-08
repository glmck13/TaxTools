// ==========================================
// GLOBAL STATE & INITIALIZATION
// ==========================================

let batchCurrentPage = 1;
let batchPageSize = 10;
const globalBatchSelections = {}; // Stores `${qboId}:${engId}` -> boolean

let currentSortColumn = null;
let currentSortAscending = true;

document.addEventListener("DOMContentLoaded", function() {
    const isBatchEnabled = Boolean(window.APP_CONFIG && window.APP_CONFIG.enableBatchMode === true);
    const modeTabsContainer = document.querySelector('.mode-tabs');
    
    if (!isBatchEnabled) {
        if (modeTabsContainer) {
            modeTabsContainer.classList.add('mode-tabs-hidden');
            modeTabsContainer.style.display = 'none';
        }
        switchWorkspaceMode('single');
    }

    // Initialize hidden engagement ID sync
    updateEngagementIdFromSelection();
});

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ==========================================
// WORKSPACE TAB & INTERACTION HELPERS
// ==========================================

function updateEngagementIdFromSelection() {
    const inputEl = document.getElementById('client-select-input');
    const hiddenEngInput = document.getElementById('engagement-id-input');
    const datalist = document.getElementById('client-select-options');

    if (!inputEl || !hiddenEngInput) return;

    const val = inputEl.value.trim();
    if (!val) {
        hiddenEngInput.value = "0";
        return;
    }

    let matchedEngId = null;

    // 1. Try matching against datalist <option> data-value="QBO_ID:ENG_ID"
    if (datalist && datalist.options) {
        for (let opt of datalist.options) {
            if (opt.value === val) {
                const dataVal = opt.getAttribute('data-value'); // Format: "58:1"
                if (dataVal && dataVal.includes(':')) {
                    matchedEngId = dataVal.split(':')[1];
                }
                break;
            }
        }
    }

    // 2. Fallback: Parse directly from string format like "[D] Client Name: 58 | 1: Title"
    if (!matchedEngId && val.includes('|')) {
        const pipeParts = val.split('|');
        if (pipeParts.length > 1) {
            const engPart = pipeParts[1].trim(); // "1: Title"
            const match = engPart.match(/^(\d+):/);
            if (match) {
                matchedEngId = match[1];
            }
        }
    }

    hiddenEngInput.value = matchedEngId ? matchedEngId : "0";
}

function switchWorkspaceMode(mode) {
    const singleTab = document.getElementById('tab-btn-single');
    const batchTab = document.getElementById('tab-btn-batch');
    const singleWorkspace = document.getElementById('single-client-workspace');
    const batchWorkspace = document.getElementById('batch-dashboard-workspace');

    if (mode === 'single') {
        if (singleTab) singleTab.classList.add('active');
        if (batchTab) batchTab.classList.remove('active');
        if (singleWorkspace) singleWorkspace.style.display = 'block';
        if (batchWorkspace) batchWorkspace.style.display = 'none';
    } else if (mode === 'batch') {
        if (batchTab) batchTab.classList.add('active');
        if (singleTab) singleTab.classList.remove('active');
        if (batchWorkspace) batchWorkspace.style.display = 'block';
        if (singleWorkspace) singleWorkspace.style.display = 'none';

        if (typeof renderBatchTableGrid === 'function') {
            renderBatchTableGrid();
        }
    }
}

function openSingleWorkspaceForClient(qboId, engId) {
    // 1. Switch active view to single client intake
    switchWorkspaceMode('single');

    // 2. Target client intake dropdown inputs
    const hiddenInput = document.getElementById('client-select');
    const visibleInput = document.getElementById('client-select-input');
    const hiddenEngInput = document.getElementById('engagement-id-input');
    const datalist = document.getElementById('client-select-options');

    if (!hiddenInput || !visibleInput) return;

    // 3. Resolve customer entry key from datalist or clientData store
    let matchedOptionValue = '';
    const targetKey = `${qboId}:${engId}`;

    if (datalist) {
        const options = datalist.querySelectorAll('option');
        for (const opt of options) {
            const dataVal = opt.getAttribute('data-value');
            if (dataVal === targetKey) {
                matchedOptionValue = opt.value;
                break;
            }
        }
        // Fallback to customer default draft if exact engagement ID match was not found
        if (!matchedOptionValue) {
            for (const opt of options) {
                const dataVal = opt.getAttribute('data-value');
                if (dataVal?.startsWith(`${qboId}:`)) {
                    matchedOptionValue = opt.value;
                    break;
                }
            }
        }
    }

    if (!matchedOptionValue && window.clientData) {
        for (const k in window.clientData) {
            if (String(window.clientData[k].id) === String(qboId)) {
                matchedOptionValue = k;
                break;
            }
        }
    }

    if (matchedOptionValue) {
        visibleInput.value = matchedOptionValue;
        hiddenInput.value = matchedOptionValue;
    } else {
        visibleInput.value = `${qboId}:${engId}`;
        hiddenInput.value = `${qboId}:${engId}`;
    }

    if (hiddenEngInput) {
        hiddenEngInput.value = String(engId || "0");
    }

    // 4. Trigger client change handler to load complete engagement view
    onClientChange();
    
    // 5. Smooth scroll to workspace top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function toggleEmailComposer() {
    const fields = document.getElementById('email-composer-fields');
    if (fields) {
        fields.style.display = (fields.style.display === 'none' || !fields.style.display) ? 'block' : 'none';
    }
}

function toggleInlineCopyBar(show) {
    const bar = document.getElementById('inline-copy-toolbar');
    if (bar) {
        bar.style.display = show ? 'block' : 'none';
    }
}

function toggleBatchBulkCopyToolbar(show) {
    const bar = document.getElementById('batch-bulk-copy-toolbar');
    if (bar) {
        bar.style.display = show ? 'block' : 'none';
    }
}

// ==========================================
// REVIEW & APPROVAL UI HELPERS (OPTION B)
// ==========================================

function getStoredReviewerInitials() {
    return (localStorage.getItem('reviewer_initials') || '').toUpperCase();
}

function setStoredReviewerInitials(initials) {
    if (initials) {
        localStorage.setItem('reviewer_initials', initials.toUpperCase());
    }
}

function renderApprovalCardHtml(draft) {
    const isApproved = Boolean(draft && draft.is_approved === true);
    const savedInitials = draft?.reviewed_by || getStoredReviewerInitials();
    const approvedAt = draft?.reviewed_at || '';

    const cardClass = isApproved ? 'approval-card-approved' : 'approval-card-unapproved';
    const checkedAttr = isApproved ? 'checked' : '';
    const dateDisplay = approvedAt ? ` on ${approvedAt}` : '';

    return `
        <div id="approval-card-container" class="approval-card ${cardClass}">
            <div class="approval-flex-container">
                <label class="approval-checkbox-label">
                    <input type="checkbox" id="is_approved_checkbox" name="is_approved" value="true" ${checkedAttr} onchange="onApprovalToggleChange(this.checked)">
                    <span>Engagement Reviewed & Approved for Dispatch</span>
                </label>
                <div class="approval-inputs-group">
                    <div class="reviewer-initials-group">
                        <label for="reviewed_by_input">Reviewer Initials:</label>
                        <input type="text" 
                               id="reviewed_by_input" 
                               name="reviewed_by" 
                               class="reviewer-initials-input" 
                               value="${escapeHtml(savedInitials)}" 
                               maxlength="3" 
                               oninput="this.value = this.value.toUpperCase().replace(/[^A-Z-]/g, ''); setStoredReviewerInitials(this.value);">
                    </div>
                    <span id="approval-meta-text" class="approval-meta-text">${isApproved ? `Approved by ${escapeHtml(savedInitials)}${dateDisplay}` : 'Awaiting manual sign-off'}</span>
                </div>
            </div>
            <input type="hidden" id="reviewed_at_input" name="reviewed_at" value="${escapeHtml(approvedAt)}">
        </div>
    `;
}

function onApprovalToggleChange(isChecked) {
    const card = document.getElementById('approval-card-container');
    const initialsInput = document.getElementById('reviewed_by_input');
    const metaText = document.getElementById('approval-meta-text');
    const timestampInput = document.getElementById('reviewed_at_input');

    if (isChecked) {
        if (card) {
            card.classList.remove('approval-card-unapproved');
            card.classList.add('approval-card-approved');
        }

        let savedInitials = getStoredReviewerInitials();
        let typedInitials = initialsInput ? initialsInput.value.trim().toUpperCase() : '';
        let currentInitials = typedInitials || savedInitials || '';

        if (initialsInput) {
            initialsInput.value = currentInitials;
        }
        if (currentInitials) {
            setStoredReviewerInitials(currentInitials);
        }

        const nowStr = new Date().toLocaleString('en-US', { month: 'short', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
        if (timestampInput) timestampInput.value = nowStr;
        if (metaText) metaText.innerText = `Approved by ${currentInitials} on ${nowStr}`;
    } else {
        if (card) {
            card.classList.remove('approval-card-approved');
            card.classList.add('approval-card-unapproved');
        }
        if (timestampInput) timestampInput.value = '';
        if (metaText) metaText.innerText = 'Awaiting manual sign-off';
    }
}

// ==========================================
// CLIENT METADATA PROFILE RENDERER
// ==========================================

function renderProfileCard(clientObj, draft, selectedEngId) {
    const container = document.getElementById('profile-healing-container');
    if (!container) return;

    const meta = clientObj.metadata || {};
    const addr = draft?.billing_address || clientObj.address || {};
    const pSigner = draft?.primary_signer || {};
    const coSigner = draft?.co_signer || {};

    const friendlyName = pSigner.friendly_name || draft?.friendly_name || meta.friendly_name || '';
    const legalName = pSigner.legal_name || draft?.legal_name || meta.friendly_name || '';
    const primaryEmail = pSigner.email || draft?.primary_signer_email || meta.primary_signer_email || clientObj.email || '';
    const phone = draft?.phone || meta.phone || clientObj.phone || '';

    const street = addr.street || addr.Line1 || '';
    const city = addr.city || addr.City || '';
    const state = addr.state || addr.CountrySubDivisionCode || '';
    const zip = addr.zip || addr.PostalCode || '';

    const entityType = draft?.entity_type || meta.entity_type || 'individual';
    const coSignerName = coSigner.name || draft?.co_signer_name || meta.co_signer_name || '';
    const coSignerEmail = coSigner.email || draft?.co_signer_email || meta.co_signer_email || '';
    const engTitle = draft?.engagement_title || '2026 Tax Services Agreement';

    container.innerHTML = `
        <div class="profile-card profile-card-complete">
            <div class="profile-card-title">Client Account & Signer Profile Metadata</div>
            
            <div class="profile-editable-grid-top">
                <div class="form-field-group engagement-title-group">
                    <label class="field-label">Engagement Document Title:</label>
                    <input type="text" id="engagement_title" name="engagement_title" value="${escapeHtml(engTitle)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Primary Signer Friendly Name:</label>
                    <input type="text" id="friendly_name" name="friendly_name" value="${escapeHtml(friendlyName)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Legal Name / Entity Title:</label>
                    <input type="text" id="legal_name" name="legal_name" value="${escapeHtml(legalName)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Primary Signer Email:</label>
                    <input type="email" id="primary_signer_email" name="primary_signer_email" value="${escapeHtml(primaryEmail)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Primary Phone Number:</label>
                    <input type="tel" id="phone" name="phone" value="${escapeHtml(phone)}">
                </div>
            </div>

            <div class="profile-editable-grid-middle">
                <div class="form-field-group">
                    <label class="field-label">Street Address:</label>
                    <input type="text" id="street" name="street" value="${escapeHtml(street)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">City:</label>
                    <input type="text" id="city" name="city" value="${escapeHtml(city)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">State:</label>
                    <input type="text" id="state" name="state" value="${escapeHtml(state)}" maxlength="2">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Zip Code:</label>
                    <input type="text" id="zip" name="zip" value="${escapeHtml(zip)}">
                </div>
            </div>

            <div class="profile-editable-grid-bottom">
                <div class="form-field-group">
                    <label class="field-label">Account Classification / Entity Type:</label>
                    <select id="entity_type" name="entity_type">
                        <option value="individual" ${entityType === 'individual' ? 'selected' : ''}>Individual Taxpayer (1040)</option>
                        <option value="s_corp" ${entityType === 's_corp' ? 'selected' : ''}>S-Corporation (1120-S)</option>
                        <option value="partnership" ${entityType === 'partnership' ? 'selected' : ''}>Partnership (1065)</option>
                        <option value="c_corp" ${entityType === 'c_corp' ? 'selected' : ''}>C-Corporation (1120)</option>
                        <option value="non_profit" ${entityType === 'non_profit' ? 'selected' : ''}>Non-Profit / Tax-Exempt (990)</option>
                        <option value="trust" ${entityType === 'trust' ? 'selected' : ''}>Trust / Estate Fiduciary (1041)</option>
                        <option value="organization" ${entityType === 'organization' ? 'selected' : ''}>Business Entity / Organization</option>
                    </select>
                </div>
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Full Name (Joint Return):</label>
                    <input type="text" id="co_signer_name" name="co_signer_name" value="${escapeHtml(coSignerName)}">
                </div>
                <div class="form-field-group">
                    <label class="field-label">Co-Signer Email Address:</label>
                    <input type="email" id="co_signer_email" name="co_signer_email" value="${escapeHtml(coSignerEmail)}">
                </div>
            </div>
        </div>
    `;

    container.style.display = 'block';
}

// ==========================================
// SINGLE CLIENT INTAKE WORKSPACE
// ==========================================

function onClientInput() {
    const input = document.getElementById('client-select-input');
    const hiddenInput = document.getElementById('client-select');
    if (!input || !hiddenInput) return;

    hiddenInput.value = input.value;
    updateEngagementIdFromSelection();
    onClientChange();
}

function onClientChange() {
    const input = document.getElementById('client-select-input');
    if (!input || !input.value) return;

    const val = input.value.trim();
    let selectedQboId = '';
    let selectedEngId = document.getElementById('engagement-id-input')?.value || '0';

    // 1. Resolve IDs from datalist options if available
    const datalist = document.getElementById('client-select-options');
    if (datalist) {
        const options = datalist.querySelectorAll('option');
        for (const opt of options) {
            if (opt.value === val) {
                const dataVal = opt.getAttribute('data-value');
                if (dataVal && dataVal.includes(':')) {
                    const parts = dataVal.split(':');
                    selectedQboId = parts[0];
                    selectedEngId = parts[1];
                }
                break;
            }
        }
    }

    // 2. Fallback: Parse string formatting directly
    if (!selectedQboId) {
        const idMatch = val.match(/:\s*(\d+)(?:\s*\||\s*$)/);
        if (idMatch) selectedQboId = idMatch[1];

        if (val.includes('|')) {
            const engMatch = val.split('|')[1].match(/^(\d+):/);
            if (engMatch) selectedEngId = engMatch[1];
        }
    }

    // 3. Fallback: Direct key or ID lookup against clientData
    if (!selectedQboId && window.clientData) {
        for (const k in window.clientData) {
            if (k === val || String(window.clientData[k].id) === val) {
                selectedQboId = String(window.clientData[k].id);
                break;
            }
        }
    }

    if (!selectedQboId) return;

    // Sync hidden engagement ID input
    const hiddenEngInput = document.getElementById('engagement-id-input');
    if (hiddenEngInput) hiddenEngInput.value = selectedEngId;

    // Load workspace client object
    let clientObj = null;
    for (const k in window.clientData) {
        if (String(window.clientData[k].id) === String(selectedQboId)) {
            clientObj = window.clientData[k];
            break;
        }
    }

    if (!clientObj) return;

    // Unhide UI containers
    const serviceTable = document.getElementById('service-table');
    const actionsContainer = document.getElementById('actions-container');
    const oosContainer = document.getElementById('out-of-scope-container');
    const submitBtn = document.getElementById('btn-submit-main');
    const lockBanner = document.getElementById('lock-banner-container');
    const syncToolbar = document.getElementById('qbo-sync-toolbar-container');
    const approvalContainer = document.getElementById('single-approval-card-container');

    if (serviceTable) serviceTable.style.display = 'table';
    if (actionsContainer) actionsContainer.style.display = 'flex';
    if (oosContainer) oosContainer.style.display = 'block';
    if (syncToolbar) syncToolbar.style.display = 'block';

    const tbody = document.getElementById('service-tbody');
    if (tbody) tbody.innerHTML = '';

    let draft = null;
    if (selectedEngId !== '0' && clientObj.engagements && clientObj.engagements[selectedEngId]) {
        draft = clientObj.engagements[selectedEngId];
    }

    // Render client metadata profile
    renderProfileCard(clientObj, draft, selectedEngId);

    if (approvalContainer) {
        approvalContainer.style.display = 'block';
        approvalContainer.innerHTML = renderApprovalCardHtml(draft);
    }

    if (lockBanner) {
        if (draft && draft.is_locked) {
            lockBanner.style.display = 'block';
            lockBanner.innerHTML = `<div style="background:#fff3cd; border:1px solid #ffebaa; color:#856404; padding:12px; margin-bottom:15px; border-radius:4px;">🔒 <strong>Engagement #${selectedEngId} is locked.</strong> Sourced on ${draft.locked_mtime}.</div>`;
        } else {
            lockBanner.style.display = 'none';
        }
    }

    // Handle form row persistence and rendering
    if (Array.isArray(window.reconstructedRows) && window.reconstructedRows.length > 0) {
        if (!clientObj.engagements) clientObj.engagements = {};
        if (!clientObj.engagements[selectedEngId]) {
            clientObj.engagements[selectedEngId] = { engagement_id: selectedEngId };
        }
        clientObj.engagements[selectedEngId].rows = JSON.parse(JSON.stringify(window.reconstructedRows));
        window.reconstructedRows.forEach(r => addServiceRow(r.item_id, r.service, r.fee, r.notes, clientObj));
        window.reconstructedRows = null;
    } else if (draft && Array.isArray(draft.rows) && draft.rows.length > 0) {
        draft.rows.forEach(r => addServiceRow(r.item_id, r.service, r.fee, r.notes, clientObj));
    } else {
        addServiceRow('', '', '', '', clientObj);
    }

    if (submitBtn) {
        submitBtn.style.display = 'inline-block';
        submitBtn.innerText = '⚡ Render PDF Preview';
    }

    recalculateTotals();
}

function addServiceRow(itemId = '', service = '', fee = '', notes = '', explicitClientObj = null) {
    const tbody = document.getElementById('service-tbody');
    if (!tbody) return;

    const rowId = Date.now() + Math.floor(Math.random() * 1000);
    const tr = document.createElement('tr');
    tr.id = `service_row_${rowId}`;

    let resolvedItemId = itemId;
    let optionsHtml = '<option value="">-- Select Service Item --</option>';

    // Use passed client object or resolve active client object safely
    let activeClientObj = explicitClientObj;
    if (!activeClientObj && window.clientData) {
        const activeInputVal = document.getElementById('client-select-input')?.value || '';
        let targetQboId = '';
        const idMatch = activeInputVal.match(/:\s*(\d+)(?:\s*\||\s*$)/);
        if (idMatch) targetQboId = idMatch[1];

        for (const k in window.clientData) {
            const client = window.clientData[k];
            if (String(client.id) === String(targetQboId) || String(client.id) === String(activeInputVal) || k === activeInputVal) {
                activeClientObj = client;
                break;
            }
        }
    }

    const clientForServices = activeClientObj || (window.clientData ? Object.values(window.clientData)[0] : null);
    if (clientForServices && Array.isArray(clientForServices.exposed_services)) {
        clientForServices.exposed_services.forEach(s => {
            const isSelectedByItemId = Boolean(itemId) && String(s.id) === String(itemId);
            const isSelectedByTitle = Boolean(service) && s.name.trim().toLowerCase() === String(service).trim().toLowerCase();
            const sel = (isSelectedByItemId || isSelectedByTitle) ? 'selected' : '';
            if (sel) {
                resolvedItemId = s.id;
            }
            optionsHtml += `<option value="${s.id}" data-service-name="${escapeHtml(s.name)}" data-fee="${s.fee}" data-notes="${escapeHtml(s.notes)}" ${sel}>${escapeHtml(s.name)} ($${s.fee})</option>`;
        });
    }

    tr.innerHTML = `
        <td style="text-align: center; width: 40px; padding-top: 16px;">
            <button type="button" class="btn-remove-row" onclick="removeServiceRow('${rowId}')" title="Remove Line">×</button>
            <input type="hidden" name="selected_rows" value="${rowId}">
            <input type="hidden" name="row_item_id_${rowId}" id="row_item_id_${rowId}" value="${escapeHtml(resolvedItemId)}">
        </td>
        <td>
            <select name="row_service_${rowId}" id="row_service_${rowId}" style="width: 100%; padding: 8px;" onchange="onServiceDropdownChange('${rowId}')">
                ${optionsHtml}
            </select>
        </td>
        <td style="white-space: nowrap; width: 140px;">
            <span style="position: relative; font-family: monospace; font-size: 15px; top: 4px;">
                $ <input type="number" name="row_fee_${rowId}" id="row_fee_${rowId}" step="1" min="-99999" value="${fee !== undefined && fee !== null ? fee : ''}" placeholder="0" oninput="recalculateTotals()" style="width: 90px; padding: 6px; margin-left: 6px;" required>
            </span>
        </td>
        <td class="notes-cell">
            <textarea name="row_notes_${rowId}" id="row_notes_${rowId}" placeholder="Enter custom line parameters or scope exclusions..." style="width: 100%; height: 46px; font-family: inherit; font-size: 13px; padding: 6px; box-sizing: border-box; resize: vertical;">${escapeHtml(notes)}</textarea>
        </td>
    `;

    tbody.appendChild(tr);

    // Enforce selection value on DOM node directly
    if (resolvedItemId) {
        const selectEl = tr.querySelector(`#row_service_${rowId}`);
        if (selectEl) selectEl.value = String(resolvedItemId);
    }

    recalculateTotals();
}

function removeServiceRow(rowId) {
    const tr = document.getElementById(`service_row_${rowId}`);
    if (tr) tr.remove();
    recalculateTotals();
}

function onServiceDropdownChange(rowId) {
    const select = document.getElementById(`row_service_${rowId}`);
    const feeInput = document.getElementById(`row_fee_${rowId}`);
    const notesInput = document.getElementById(`row_notes_${rowId}`);
    const itemIdHidden = document.getElementById(`row_item_id_${rowId}`);

    if (!select) return;

    const opt = select.options[select.selectedIndex];
    if (opt && opt.value) {
        if (itemIdHidden) itemIdHidden.value = opt.value;
        if (feeInput) {
            feeInput.value = opt.getAttribute('data-fee') || '0';
        }
        if (notesInput) {
            notesInput.value = opt.getAttribute('data-notes') || '';
        }
    } else {
        if (itemIdHidden) itemIdHidden.value = '';
        if (feeInput) feeInput.value = '0';
        if (notesInput) notesInput.value = '';
    }
    recalculateTotals();
}

function recalculateTotals() {
    let baseTotal = 0;
    let discountTotal = 0;

    const tbody = document.getElementById('service-tbody');
    if (!tbody) return;

    const rows = tbody.querySelectorAll('tr');
    rows.forEach(tr => {
        const feeInput = tr.querySelector('input[type="number"]');
        const select = tr.querySelector('select');
        if (feeInput) {
            const val = parseInt(feeInput.value, 10) || 0;
            
            let serviceText = '';
            if (select && select.selectedIndex >= 0) {
                const opt = select.options[select.selectedIndex];
                serviceText = (opt?.getAttribute('data-service-name') || opt?.text || opt?.value || '').toLowerCase();
            }

            if (serviceText.includes('discount') || serviceText.includes('referral')) {
                discountTotal += Math.abs(val);
            } else {
                baseTotal += val;
            }
        }
    });

    const netTotal = baseTotal - discountTotal;
    const discountEl = document.getElementById('ui-total-discount');
    const balanceEl = document.getElementById('ui-total-balance');

    if (discountEl) discountEl.innerText = `-$${discountTotal.toLocaleString()}`;
    if (balanceEl) balanceEl.innerText = `$${netTotal.toLocaleString()}`;
}

function addCustomOutOfScopeItem() {
    const input = document.getElementById('new-out-of-scope-input');
    const container = document.getElementById('out-of-scope-checklist-container');

    if (!input || !container || !input.value.trim()) return;

    const val = input.value.trim();
    const itemKey = `custom_out_of_scope_${Date.now()}`;

    const div = document.createElement('div');
    div.className = 'out-of-scope-checklist-item custom-out-of-scope-item';
    div.style.cssText = 'display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0;';
    div.innerHTML = `
        <label style="font-weight: normal; display: flex; align-items: center; gap: 8px; cursor: pointer; flex-grow: 1;">
            <input type="checkbox" name="${itemKey}" value="${escapeHtml(val)}" checked>
            <span>${escapeHtml(val)}</span>
        </label>
        <button type="button" class="btn-remove-row" onclick="this.parentElement.remove()" title="Remove Custom Exclusion" style="margin-left: 10px;">×</button>
    `;

    container.appendChild(div);
    input.value = '';
}

function applyClonedScopeFromSource() {
    const sourceInput = document.getElementById('clone-source-input');
    if (!sourceInput || !sourceInput.value) return alert('Select a source engagement to copy scope from.');

    const sourceVal = sourceInput.value.trim();
    const parts = sourceVal.split(':');
    if (parts.length < 2) return alert('Invalid source selection format.');

    const qboId = parts[0];
    const engId = parts[1];

    let sourceDraft = null;
    for (const k in window.clientData) {
        if (String(window.clientData[k].id) === String(qboId)) {
            sourceDraft = window.clientData[k].engagements?.[engId];
            break;
        }
    }

    if (!sourceDraft || !sourceDraft.rows) return alert('Could not locate scope rows in source engagement.');

    const tbody = document.getElementById('service-tbody');
    if (tbody) tbody.innerHTML = '';

    sourceDraft.rows.forEach(r => addServiceRow(r.item_id, r.service, r.fee, r.notes));
    toggleInlineCopyBar(false);
}

// ==========================================
// BATCH DASHBOARD WORKSPACE (PAGINATED MODEL)
// ==========================================

function setBatchPageSize(size) {
    batchPageSize = (size === 'all') ? 'all' : parseInt(size, 10);
    batchCurrentPage = 1;

    document.querySelectorAll('.page-size-selector').forEach(sel => {
        sel.value = size;
    });

    renderBatchTableGrid();
}

function changeBatchPage(direction) {
    const filteredRows = getFilteredBatchRows();
    if (batchPageSize === 'all') return;

    const totalPages = Math.max(1, Math.ceil(filteredRows.length / batchPageSize));

    if (direction === 'first') batchCurrentPage = 1;
    else if (direction === 'prev' && batchCurrentPage > 1) batchCurrentPage--;
    else if (direction === 'next' && batchCurrentPage < totalPages) batchCurrentPage++;
    else if (direction === 'last') batchCurrentPage = totalPages;

    renderBatchTableGrid();
}

function handleBatchCheckboxToggle(qboId, engId, isChecked) {
    const key = `${qboId}:${engId}`;
    globalBatchSelections[key] = isChecked;
    updateBatchSummaryMetrics();
}

function sortBatchTable(columnIndex) {
    if (currentSortColumn === columnIndex) {
        currentSortAscending = !currentSortAscending;
    } else {
        currentSortColumn = columnIndex;
        currentSortAscending = true;
    }
    renderBatchTableGrid();
}

function getFilteredBatchRows() {
    if (!window.clientData) return [];

    const searchQuery = (document.getElementById('batch-search-input')?.value || '').toLowerCase();
    const formatFilter = document.getElementById('batch-format-filter')?.value || 'all';
    const allRecords = [];

    Object.keys(window.clientData).forEach(clientKey => {
        const client = window.clientData[clientKey];
        const qboId = String(client.id);
        const meta = client.metadata || {};
        const clientAddr = client.address || {};
        const engagements = client.engagements || {};

        Object.keys(engagements).forEach(engId => {
            const draft = engagements[engId];
            const isLocked = Boolean(draft.is_locked);
            const effectiveFormat = draft.delivery_format || meta.delivery_format || 'electronic';
            const isPaper = (effectiveFormat === 'paper');

            let clientFee = 0.0;
            if (draft.rows && draft.rows.length > 0) {
                const baseFee = draft.rows.reduce((sum, r) => sum + (r.fee || 0), 0);
                const discountFee = draft.rows.filter(r => (r.service || '').toLowerCase().includes('discount')).reduce((sum, r) => sum + Math.abs(r.fee || 0), 0);
                clientFee = baseFee - discountFee;
            }

            const pSigner = draft.primary_signer || {};
            const coSigner = draft.co_signer || {};
            const addrObj = draft.billing_address || clientAddr;

            const hasServiceRows = Boolean(draft.rows && Array.isArray(draft.rows) && draft.rows.length > 0);
            const isAddressMissing = !addrObj.street || !addrObj.city;
            const isConfigMissing = !draft.entity_type && !meta.entity_type;
            const isEmailMissing = !pSigner.email && !draft.primary_signer_email && !client.email;
            const isDataIncomplete = !hasServiceRows || isAddressMissing || isConfigMissing || isEmailMissing;

            const isApproved = Boolean(draft.is_approved === true);
            const reviewedBy = draft.reviewed_by || '';
            const reviewedAt = draft.reviewed_at || '';

            const entityType = draft.entity_type || meta.entity_type || 'individual';
            const engTitle = draft.engagement_title || `Engagement #${engId}`;

            const coSignerEmailVal = coSigner.email || draft.co_signer_email || meta.co_signer_email || '';
            const coSignerNameVal = coSigner.name || draft.co_signer_name || meta.co_signer_name || '';
            const isDualSigner = (coSignerEmailVal.includes('@') || coSignerNameVal.length > 0);
            const clientNameClean = pSigner.friendly_name || draft.friendly_name || meta.friendly_name || clientKey.split(' (Customer')[0];

            const searchableText = `${qboId} ${clientNameClean} ${engTitle} ${entityType} ${clientFee} ${reviewedBy}`.toLowerCase();

            const matchesSearch = searchableText.includes(searchQuery);
            let matchesFormat = true;
            if (formatFilter === 'paper') matchesFormat = isPaper;
            if (formatFilter === 'electronic') matchesFormat = !isPaper;

            if (matchesSearch && matchesFormat) {
                allRecords.push({
                    qboId, engId, clientKey, client, draft, isLocked, isPaper,
                    clientFee, entityType, isDualSigner, coSignerNameVal, coSignerEmailVal,
                    isDataIncomplete, isApproved, reviewedBy, reviewedAt, clientNameClean, engTitle
                });
            }
        });
    });

    if (currentSortColumn !== null) {
        allRecords.sort((a, b) => {
            let valA, valB;
            switch (currentSortColumn) {
                case 1: valA = parseInt(a.qboId, 10) || 0; valB = parseInt(b.qboId, 10) || 0; break;
                case 2: valA = a.clientNameClean.toLowerCase(); valB = b.clientNameClean.toLowerCase(); break;
                case 3: valA = (a.entityType || '').toLowerCase(); valB = (b.entityType || '').toLowerCase(); break;
                case 4: valA = a.isDualSigner ? 1 : 0; valB = b.isDualSigner ? 1 : 0; break;
                case 5: valA = a.clientFee; valB = b.clientFee; break;
                case 6: valA = a.isPaper ? 1 : 0; valB = b.isPaper ? 1 : 0; break;
                case 7: valA = a.isLocked ? 3 : (a.isDataIncomplete ? 0 : (a.isApproved ? 2 : 1)); valB = b.isLocked ? 3 : (b.isDataIncomplete ? 0 : (b.isApproved ? 2 : 1)); break;
                default: valA = 0; valB = 0;
            }

            let comparison = (typeof valA === 'number' && typeof valB === 'number')
                ? valA - valB
                : String(valA).localeCompare(String(valB));

            return currentSortAscending ? comparison : -comparison;
        });
    }

    return allRecords;
}

function renderBatchTableGrid() {
    const tbody = document.getElementById('batch-tbody');
    if (!tbody || !window.clientData) return;

    const filteredRows = getFilteredBatchRows();
    const totalFilteredCount = filteredRows.length;

    filteredRows.forEach(item => {
        const key = `${item.qboId}:${item.engId}`;
        if (!Object.prototype.hasOwnProperty.call(globalBatchSelections, key)) {
            globalBatchSelections[key] = (!item.isLocked && !item.isDataIncomplete && item.isApproved);
        }
    });

    let paginatedSlice = filteredRows;
    if (batchPageSize !== 'all') {
        const totalPages = Math.max(1, Math.ceil(totalFilteredCount / batchPageSize));
        if (batchCurrentPage > totalPages) batchCurrentPage = totalPages;

        const startIndex = (batchCurrentPage - 1) * batchPageSize;
        paginatedSlice = filteredRows.slice(startIndex, startIndex + batchPageSize);
    }

    tbody.innerHTML = '';

    paginatedSlice.forEach(item => {
        const { qboId, engId, isLocked, isPaper, clientFee, entityType, isDualSigner, coSignerNameVal, coSignerEmailVal, isDataIncomplete, isApproved, reviewedBy, clientNameClean, engTitle } = item;
        const selectionKey = `${qboId}:${engId}`;
        const isChecked = Boolean(globalBatchSelections[selectionKey]);

        const badgeClickAttr = `onclick="openBatchEditModal('${qboId}', '${engId}')" title="Click to review services and fees"`;

        let statusBadge = `<span class="badge badge-needs-review badge-clickable" ${badgeClickAttr}>🔍 Needs Review</span>`;
        let checkboxDisabled = '';

        if (isLocked) {
            statusBadge = '<span class="badge badge-locked">🔒 Sent</span>';
            checkboxDisabled = 'disabled';
        } else if (isDataIncomplete) {
            statusBadge = `<span class="badge badge-warning badge-clickable" ${badgeClickAttr}>⚠️ Data Incomplete</span>`;
            checkboxDisabled = 'disabled';
        } else if (isApproved) {
            const byText = reviewedBy ? ` (${escapeHtml(reviewedBy)})` : '';
            statusBadge = `<span class="badge badge-approved badge-clickable" ${badgeClickAttr}>✅ Approved${byText}</span>`;
        } else {
            checkboxDisabled = 'disabled';
        }

        const checkedAttr = (isChecked && !checkboxDisabled) ? 'checked' : '';
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

        const tr = document.createElement('tr');
        tr.id = `batch_row_${qboId}_${engId}`;
        tr.className = `batch-row-item format-${isPaper ? 'paper' : 'electronic'}`;
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="batch-checkbox" data-qbo-id="${qboId}" data-eng-id="${engId}" ${checkboxDisabled} ${checkedAttr} onchange="handleBatchCheckboxToggle('${qboId}', '${engId}', this.checked)">
            </td>
            <td style="font-family: monospace; font-size: 12px; color: #555;">${qboId}</td>
            <td style="padding: 4px 8px;">
                <a href="javascript:void(0)" 
                   onclick="openSingleWorkspaceForClient('${qboId}', '${engId}')" 
                   style="color: #0078d4; font-weight: 700; text-decoration: underline; cursor: pointer;"
                   title="Open Full Single Engagement Workspace">
                    ${escapeHtml(clientNameClean)}
                </a>
                <br/><small style="color: #475569; font-weight: 600;">${escapeHtml(engTitle)}</small>
            </td>
            <td><span class="badge ${entityType === 'individual' ? 'badge-individual' : 'badge-organization'}">${escapeHtml(entityType)}</span></td>
            <td style="font-size: 12px; color: #444;">${isDualSigner ? 'Joint (' + escapeHtml(coSignerNameVal || coSignerEmailVal) + ')' : 'Single'}</td>
            <td style="text-align: right; font-family: monospace; font-weight: bold; font-size: 14px;">$${Math.round(clientFee).toLocaleString()}</td>
            <td>${formatBadgeHtml}</td>
            <td>${statusBadge}</td>
        `;
        tbody.appendChild(tr);
    });

    updateSortIndicators();
    updatePaginationUI(totalFilteredCount);
    updateBatchSummaryMetrics();
}

function updateSortIndicators() {
    document.querySelectorAll('.batch-table th.sortable-th').forEach(th => {
        const thColIdx = parseInt(th.getAttribute('data-col-index'), 10);
        const indicator = th.querySelector('.sort-indicator');
        if (indicator) {
            indicator.innerText = (thColIdx === currentSortColumn) ? (currentSortAscending ? ' ▲' : ' ▼') : ' ⇅';
        }
    });
}

function updatePaginationUI(totalItems) {
    const pageInfos = document.querySelectorAll('.batch-page-info');
    const prevBtns = document.querySelectorAll('.btn-prev-page');
    const nextBtns = document.querySelectorAll('.btn-next-page');

    if (batchPageSize === 'all') {
        pageInfos.forEach(el => el.innerText = `Showing all ${totalItems} engagements`);
        prevBtns.forEach(btn => btn.disabled = true);
        nextBtns.forEach(btn => btn.disabled = true);
        return;
    }

    const totalPages = Math.max(1, Math.ceil(totalItems / batchPageSize));
    const startNum = totalItems === 0 ? 0 : (batchCurrentPage - 1) * batchPageSize + 1;
    const endNum = Math.min(batchCurrentPage * batchPageSize, totalItems);

    pageInfos.forEach(el => el.innerText = `Showing ${startNum}–${endNum} of ${totalItems} engagements (Page ${batchCurrentPage} of ${totalPages})`);
    prevBtns.forEach(btn => btn.disabled = (batchCurrentPage <= 1));
    nextBtns.forEach(btn => btn.disabled = (batchCurrentPage >= totalPages));
}

function updateBatchSummaryMetrics() {
    if (!window.clientData) return;

    let selectedCount = 0, selectedElectronic = 0, selectedPaper = 0;
    let approvedCount = 0;
    let needsReviewCount = 0;
    let incompleteCount = 0;
    let sentCount = 0;

    Object.keys(window.clientData).forEach(clientKey => {
        const client = window.clientData[clientKey];
        const qboId = String(client.id);
        const meta = client.metadata || {};
        const clientAddr = client.address || {};
        const engagements = client.engagements || {};

        Object.keys(engagements).forEach(engId => {
            const draft = engagements[engId];
            const isLocked = Boolean(draft.is_locked);
            const effectiveFormat = draft.delivery_format || meta.delivery_format || 'electronic';
            const isPaper = (effectiveFormat === 'paper');

            const pSigner = draft.primary_signer || {};
            const addrObj = draft.billing_address || clientAddr;

            const hasServiceRows = Boolean(draft.rows && Array.isArray(draft.rows) && draft.rows.length > 0);
            const isAddressMissing = !addrObj.street || !addrObj.city;
            const isConfigMissing = !draft.entity_type && !meta.entity_type;
            const isEmailMissing = !pSigner.email && !draft.primary_signer_email && !client.email;
            const isDataIncomplete = !hasServiceRows || isAddressMissing || isConfigMissing || isEmailMissing;

            const isApproved = Boolean(draft.is_approved === true);

            const selectionKey = `${qboId}:${engId}`;
            const isChecked = Boolean(globalBatchSelections[selectionKey]);

            if (isChecked && isApproved && !isLocked && !isDataIncomplete) {
                selectedCount++;
                if (isPaper) selectedPaper++; else selectedElectronic++;
            }

            if (isLocked) {
                sentCount++;
            } else if (isDataIncomplete) {
                incompleteCount++;
            } else if (isApproved) {
                approvedCount++;
            } else {
                needsReviewCount++;
            }
        });
    });

    const summaryGridNode = document.getElementById('batch-summary-grid');
    if (summaryGridNode) {
        summaryGridNode.innerHTML = `
            <div class="summary-strip-item">
                <span class="strip-label">Selected Batch:</span>
                <span class="strip-value">${selectedCount}</span>
                <span class="strip-sub">(${selectedElectronic} E-Sign / ${selectedPaper} Paper)</span>
            </div>
            <div class="summary-strip-divider">|</div>
            <div class="summary-strip-item">
                <span class="strip-label">Approved / Ready:</span>
                <span class="strip-value text-green">${approvedCount}</span>
            </div>
            <div class="summary-strip-divider">|</div>
            <div class="summary-strip-item">
                <span class="strip-label">Needs Review:</span>
                <span class="strip-value text-orange">${needsReviewCount}</span>
            </div>
            <div class="summary-strip-divider">|</div>
            <div class="summary-strip-item">
                <span class="strip-label">Data Incomplete:</span>
                <span class="strip-value text-orange">${incompleteCount}</span>
            </div>
            <div class="summary-strip-divider">|</div>
            <div class="summary-strip-item">
                <span class="strip-label">Dispatched / Sent:</span>
                <span class="strip-value text-blue">${sentCount}</span>
            </div>
        `;
    }
}

function filterBatchTableGrid() {
    batchCurrentPage = 1;
    renderBatchTableGrid();
}

function selectAllBatchRows(shouldSelect) {
    const filteredRows = getFilteredBatchRows();
    filteredRows.forEach(item => {
        if (!item.isLocked && !item.isDataIncomplete && item.isApproved) {
            globalBatchSelections[`${item.qboId}:${item.engId}`] = shouldSelect;
        }
    });
    renderBatchTableGrid();
}

function toggleClientDeliveryFormat(qboId, engId) {
    let targetDraft = null;
    for (const k in window.clientData) {
        if (String(window.clientData[k].id) === String(qboId)) {
            targetDraft = window.clientData[k].engagements?.[engId];
            break;
        }
    }

    if (!targetDraft || targetDraft.is_locked) return;

    // Flip value in memory
    const newFmt = (targetDraft.delivery_format === 'paper') ? 'electronic' : 'paper';
    targetDraft.delivery_format = newFmt;

    // Optimistically update UI
    renderBatchTableGrid();

    // Dispatch minimal patch payload
    const params = new URLSearchParams();
    params.append('action', 'patch_draft_only');
    params.append('client_name', qboId);
    params.append('engagement_id', engId);
    params.append('delivery_format', newFmt);

    fetch(window.location.href, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString()
    }).catch(err => console.error('Error saving format preference:', err));
}

// ==========================================
// BATCH MODAL EDITING & BULK ACTIONS
// ==========================================

function openBatchEditModal(qboId, engId) {
    const modal = document.getElementById('batch-edit-modal');
    const container = document.getElementById('modal-workspace-container');
    if (!modal || !container) return;

    let clientObj = null;
    let clientKeyName = '';
    for (const k in window.clientData) {
        if (String(window.clientData[k].id) === String(qboId)) {
            clientObj = window.clientData[k];
            clientKeyName = k;
            break;
        }
    }

    if (!clientObj) return;

    const draft = clientObj.engagements?.[engId] || {};
    const titleEl = document.getElementById('modal-client-title');
    
    if (titleEl) {
        titleEl.innerText = `Quick Review & Sign-Off: ${clientKeyName.split(' (Customer')[0]} (#${engId})`;
    }

    container.setAttribute('data-qbo-id', qboId);
    container.setAttribute('data-eng-id', engId);

    let serviceRowsHtml = '';
    const rows = (draft.rows && draft.rows.length > 0) ? draft.rows : [{ item_id: '', service: '', fee: '', notes: '' }];

    rows.forEach((r) => {
        const rowId = `m_${Date.now()}_${Math.floor(Math.random() * 1000)}`;
        let optionsHtml = '<option value="">-- Select Service Item --</option>';
        let resolvedItemId = r.item_id || '';

        if (clientObj.exposed_services) {
            clientObj.exposed_services.forEach(s => {
                const isSelectedByItemId = Boolean(r.item_id) && String(s.id) === String(r.item_id);
                const isSelectedByTitle = Boolean(r.service) && s.name.trim().toLowerCase() === String(r.service).trim().toLowerCase();
                const sel = (isSelectedByItemId || isSelectedByTitle) ? 'selected' : '';
                if (sel) {
                    resolvedItemId = s.id;
                }
                optionsHtml += `<option value="${s.id}" data-service-name="${escapeHtml(s.name)}" data-fee="${s.fee}" data-notes="${escapeHtml(s.notes)}" ${sel}>${escapeHtml(s.name)} ($${s.fee})</option>`;
            });
        }

        serviceRowsHtml += `
            <tr id="service_row_${rowId}">
                <td style="text-align: center; width: 40px; padding-top: 16px;">
                    <button type="button" class="btn-remove-row" onclick="removeServiceRow('${rowId}')" title="Remove Line Item">×</button>
                    <input type="hidden" name="selected_rows" value="${rowId}">
                    <input type="hidden" name="row_item_id_${rowId}" id="row_item_id_${rowId}" value="${escapeHtml(resolvedItemId)}">
                </td>
                <td>
                    <select name="row_service_${rowId}" id="row_service_${rowId}" style="width: 100%; padding: 8px;" onchange="onServiceDropdownChange('${rowId}')">
                        ${optionsHtml}
                    </select>
                </td>
                <td style="white-space: nowrap; width: 140px;">
                    <span style="position: relative; font-family: monospace; font-size: 15px; top: 4px;">
                        $ <input type="number" name="row_fee_${rowId}" id="row_fee_${rowId}" step="1" min="-99999" value="${r.fee !== undefined && r.fee !== null ? r.fee : ''}" placeholder="0" oninput="recalculateTotals()" style="width: 90px; padding: 6px; margin-left: 6px;" required>
                    </span>
                </td>
                <td class="notes-cell">
                    <textarea name="row_notes_${rowId}" id="row_notes_${rowId}" placeholder="Scope notes or specifications..." style="width: 100%; height: 46px; font-family: inherit; font-size: 13px; padding: 6px; box-sizing: border-box; resize: vertical;">${escapeHtml(r.notes || '')}</textarea>
                </td>
            </tr>
        `;
    });

    container.innerHTML = `
        <div style="margin-bottom: 12px;">
            ${renderApprovalCardHtml(draft)}
        </div>

        <table class="service-table" style="width: 100%; margin-top: 10px; margin-bottom: 15px;">
            <thead>
                <tr>
                    <th style="text-align:center; width:45px;">Action</th>
                    <th style="width:30%;">Service Item Offering</th>
                    <th style="width:140px; text-align:right; white-space:nowrap;">Proposed Amount</th>
                    <th>Scope Specification / Notes</th>
                </tr>
            </thead>
            <tbody id="service-tbody">
                ${serviceRowsHtml}
            </tbody>
            <tfoot>
                <tr style="background:#fafafa;">
                    <td colspan="2" style="text-align:right; font-weight:700; padding:10px; color:#b76200;">Client Discount:</td>
                    <td id="ui-total-discount" class="calc-val" style="padding:10px; text-align:right; color:#b76200;">-$0</td>
                    <td></td>
                </tr>
                <tr class="calc-row-balance">
                    <td colspan="2" style="text-align:right; font-weight:700; padding:10px;">TOTAL FEES:</td>
                    <td id="ui-total-balance" class="calc-val" style="padding:10px; text-align:right;">$0</td>
                    <td></td>
                </tr>
            </tfoot>
        </table>

        <div style="margin-bottom: 15px;">
            <button type="button" class="btn-add-row" onclick="addServiceRow()">+ Add Service Line Item</button>
        </div>
    `;

    modal.style.display = 'flex';
    recalculateTotals();
}

function closeBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    const container = document.getElementById('modal-workspace-container');
    
    if (container) {
        const qboId = container.getAttribute('data-qbo-id');
        const engId = container.getAttribute('data-eng-id');
        
        const isApprovedCheckbox = container.querySelector('#is_approved_checkbox') || document.getElementById('is_approved_checkbox');
        const initialsInput = container.querySelector('#reviewed_by_input') || document.getElementById('reviewed_by_input');
        const timestampInput = container.querySelector('#reviewed_at_input') || document.getElementById('reviewed_at_input');

        if (qboId && engId) {
            let clientObj = null;
            for (const k in window.clientData) {
                if (String(window.clientData[k].id) === String(qboId)) {
                    clientObj = window.clientData[k];
                    break;
                }
            }

            if (clientObj && clientObj.engagements?.[engId]) {
                const targetDraft = clientObj.engagements[engId];
                const newApprovedState = Boolean(isApprovedCheckbox && isApprovedCheckbox.checked);
                
                targetDraft.is_approved = newApprovedState;
                targetDraft.reviewed_by = initialsInput ? initialsInput.value.trim().toUpperCase() : '';
                targetDraft.reviewed_at = timestampInput ? timestampInput.value.trim() : '';

                const modalRows = [];
                const tbody = container.querySelector('#service-tbody');
                if (tbody) {
                    const trs = tbody.querySelectorAll('tr');
                    trs.forEach(tr => {
                        const rowIdInput = tr.querySelector('input[name="selected_rows"]');
                        if (rowIdInput) {
                            const rowId = rowIdInput.value;
                            const itemId = tr.querySelector(`#row_item_id_${rowId}`)?.value || '';
                            const selectEl = tr.querySelector(`#row_service_${rowId}`);
                            
                            let serviceName = '';
                            if (selectEl && selectEl.selectedIndex >= 0) {
                                const selectedOption = selectEl.options[selectEl.selectedIndex];
                                const attrName = selectedOption.getAttribute('data-service-name');
                                if (attrName) {
                                    serviceName = attrName.trim();
                                } else {
                                    const rawText = selectedOption.text || '';
                                    serviceName = rawText.replace(/\s*\(\$[\d,]+\)$/, '').trim();
                                }
                            }

                            const fee = parseInt(tr.querySelector(`#row_fee_${rowId}`)?.value, 10) || 0;
                            const notes = tr.querySelector(`#row_notes_${rowId}`)?.value || '';
                            if (itemId || serviceName) {
                                modalRows.push({ item_id: itemId, service: serviceName, fee: fee, notes: notes });
                            }
                        }
                    });
                    
                    targetDraft.rows = modalRows;
                }

                const params = new URLSearchParams();
                params.append('action', 'patch_draft_only');
                params.append('client_name', qboId);
                params.append('engagement_id', engId);
                params.append('is_approved', newApprovedState ? 'true' : 'false');
                params.append('reviewed_by', targetDraft.reviewed_by || '');
                params.append('reviewed_at', targetDraft.reviewed_at || '');

                const safeRows = Array.isArray(targetDraft.rows) ? targetDraft.rows : [];
                safeRows.forEach((r, idx) => {
                    const rid = idx + 1;
                    params.append('selected_rows', rid);
                    params.append(`row_item_id_${rid}`, r.item_id || '');
                    params.append(`row_service_${rid}`, r.service || '');
                    params.append(`row_fee_${rid}`, r.fee || 0);
                    params.append(`row_notes_${rid}`, r.notes || '');
                });

                const isDataIncomplete = !targetDraft.rows?.length || !targetDraft.primary_signer?.email;
                globalBatchSelections[`${qboId}:${engId}`] = newApprovedState && !isDataIncomplete;

                fetch(window.location.href, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: params.toString()
                })
                .then(() => {
                    renderBatchTableGrid();
                })
                .catch(err => console.error('Error saving engagement draft:', err));
            }
        }
        
        container.innerHTML = '';
    }

    if (modal) modal.style.display = 'none';
    renderBatchTableGrid();
}

function cancelBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    const container = document.getElementById('modal-workspace-container');
    if (modal) modal.style.display = 'none';
    if (container) container.innerHTML = '';
}

function applyBatchBulkClonedScope() {
    const sourceVal = document.getElementById('batch-bulk-source-input')?.value || '';
    if (!sourceVal) return alert('Please select a source engagement to copy scope from.');

    const targetKeys = Object.keys(globalBatchSelections).filter(k => globalBatchSelections[k] === true);
    if (targetKeys.length === 0) return alert('No batch engagements selected.');

    const parts = sourceVal.split(':');
    if (parts.length < 2) return alert('Invalid source selection format.');

    const sourceQboId = parts[0];
    const sourceEngId = parts[1];

    let sourceDraft = null;
    for (const k in window.clientData) {
        if (String(window.clientData[k].id) === String(sourceQboId)) {
            sourceDraft = window.clientData[k].engagements?.[sourceEngId];
            break;
        }
    }

    if (!sourceDraft || !sourceDraft.rows) return alert('Source engagement has no rows to copy.');

    if (!confirm(`Apply cloned scope (${sourceDraft.rows.length} item(s)) to ${targetKeys.length} checked batch engagement(s)?`)) return;

    const overlay = document.getElementById('batch-progress-overlay');
    const terminalLog = document.getElementById('batch-terminal-log');
    const progressBar = document.getElementById('batch-progress-fill');
    const closeBtn = document.getElementById('btn-close-progress');

    if (overlay) overlay.style.display = 'flex';
    if (closeBtn) closeBtn.style.display = 'none';
    if (terminalLog) terminalLog.innerHTML = `Cloning scope to ${targetKeys.length} engagement file(s)...\n`;

    let completed = 0;

    targetKeys.forEach(key => {
        const [qboId, engId] = key.split(':');
        let targetDraft = null;
        for (const k in window.clientData) {
            if (String(window.clientData[k].id) === String(qboId)) {
                targetDraft = window.clientData[k].engagements?.[engId];
                break;
            }
        }

        if (targetDraft) {
            targetDraft.rows = JSON.parse(JSON.stringify(sourceDraft.rows));
            if (sourceDraft.out_of_scope_items) {
                targetDraft.out_of_scope_items = JSON.parse(JSON.stringify(sourceDraft.out_of_scope_items));
            }
        }

        completed++;
        if (progressBar) progressBar.style.width = `${(completed / targetKeys.length) * 100}%`;
        if (terminalLog) terminalLog.innerHTML += `\n[${completed}/${targetKeys.length}] Updated QBO ${qboId} / Eng ${engId}`;
    });

    if (terminalLog) terminalLog.innerHTML += `\n\n========================================\nScope clone execution complete!`;
    if (closeBtn) closeBtn.style.display = 'inline-block';
}

async function executeBatchPipelineSubmission() {
    const targetKeys = Object.keys(globalBatchSelections).filter(k => globalBatchSelections[k] === true);
    if (targetKeys.length === 0) return alert('No valid, approved engagements selected.');

    if (!confirm(`Are you sure you want to process and dispatch ${targetKeys.length} approved engagement(s)?`)) return;

    const overlay = document.getElementById('batch-progress-overlay');
    const terminalLog = document.getElementById('batch-terminal-log');
    const progressBar = document.getElementById('batch-progress-fill');
    const closeBtn = document.getElementById('btn-close-progress');

    if (overlay) overlay.style.display = 'flex';
    if (closeBtn) closeBtn.style.display = 'none';
    if (terminalLog) terminalLog.innerHTML = `Starting batch process for ${targetKeys.length} engagement(s)...\n`;

    let completed = 0;

    for (const key of targetKeys) {
        const [qboId, engId] = key.split(':');
        
        let clientKey = '';
        let clientObj = null;
        for (const k in window.clientData) {
            if (String(window.clientData[k].id) === String(qboId)) {
                clientObj = window.clientData[k];
                clientKey = k;
                break;
            }
        }
        
        const draft = clientObj?.engagements?.[engId] || {};
        const isPaper = (draft.delivery_format === 'paper');
        
        const params = new URLSearchParams();
        params.append('ajax', 'true');
        params.append('action', isPaper ? 'execute_transactional_pipeline_paper' : 'execute_transactional_pipeline');
        params.append('client_name', clientKey || qboId);
        params.append('engagement_id', engId);
        params.append('engagement_title', draft.engagement_title || '2026 Tax Services Agreement');
        params.append('delivery_format', draft.delivery_format || 'electronic');

        // Signer & Contact Information
        const pSigner = draft.primary_signer || {};
        const coSigner = draft.co_signer || {};
        const bAddr = draft.billing_address || {};

        params.append('friendly_name', pSigner.friendly_name || draft.friendly_name || clientObj?.metadata?.friendly_name || '');
        params.append('legal_name', pSigner.legal_name || draft.legal_name || '');
        params.append('primary_signer_email', pSigner.email || draft.primary_signer_email || clientObj?.metadata?.primary_signer_email || clientObj?.email || '');
        params.append('co_signer_name', coSigner.name || draft.co_signer_name || clientObj?.metadata?.co_signer_name || '');
        params.append('co_signer_email', coSigner.email || draft.co_signer_email || clientObj?.metadata?.co_signer_email || '');
        params.append('phone', draft.phone || clientObj?.metadata?.phone || clientObj?.phone || '');
        params.append('entity_type', draft.entity_type || clientObj?.metadata?.entity_type || 'individual');

        params.append('street', bAddr.street || clientObj?.address?.street || '');
        params.append('city', bAddr.city || clientObj?.address?.city || '');
        params.append('state', bAddr.state || clientObj?.address?.state || '');
        params.append('zip', bAddr.zip || clientObj?.address?.zip || '');

        // Service Line Items
        if (Array.isArray(draft.rows)) {
            draft.rows.forEach((r, idx) => {
                const rid = idx + 1;
                params.append('selected_rows', rid);
                params.append(`row_item_id_${rid}`, r.item_id || '');
                params.append(`row_service_${rid}`, r.service || '');
                params.append(`row_fee_${rid}`, Math.round(parseFloat(r.fee || 0)));
                params.append(`row_notes_${rid}`, r.notes || '');
                params.append(`row_bp_${rid}`, r.bp || 'individual');
            });
        }

        // Out of Scope Items
        params.append('oos_submitted', 'true');
        if (draft.out_of_scope_items && typeof draft.out_of_scope_items === 'object') {
            Object.entries(draft.out_of_scope_items).forEach(([k, v]) => {
                params.append(k, v);
            });
        }

        terminalLog.innerHTML += `\n[${completed + 1}/${targetKeys.length}] Processing QBO ID ${qboId} / Eng ${engId} (${isPaper ? 'PAPER' : 'E-SIGN'})... `;
        
        try {
            const res = await fetch(window.location.href, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: params.toString()
            });

            if (res.ok) {
                const data = await res.json();
                if (data.status === 'success') {
                    if (draft) draft.is_locked = true;
                    terminalLog.innerHTML += `SUCCESS ✔ (Estimate #${data.estimate_id || 'OK'})`;
                } else {
                    terminalLog.innerHTML += `FAILED ❌ (${data.message || 'Pipeline failed'})`;
                }
            } else {
                let errDetail = `HTTP ${res.status}`;
                try {
                    const errData = await res.json();
                    if (errData.message) errDetail = errData.message;
                } catch(e) {}
                terminalLog.innerHTML += `FAILED ❌ (${errDetail})`;
            }
        } catch (err) {
            terminalLog.innerHTML += `ERROR ❌ (${err.message})`;
        }

        completed++;
        progressBar.style.width = `${(completed / targetKeys.length) * 100}%`;
        terminalLog.scrollTop = terminalLog.scrollHeight;
    }

    terminalLog.innerHTML += `\n\n========================================\nBatch pipeline execution complete!`;
    closeBtn.style.display = 'inline-block';
}
