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
// SINGLE CLIENT INTAKE WORKSPACE
// ==========================================

function onClientInput() {
    const input = document.getElementById('client-select-input');
    const hiddenInput = document.getElementById('client-select');
    if (!input || !hiddenInput) return;

    hiddenInput.value = input.value;
    onClientChange();
}

function onClientChange() {
    const input = document.getElementById('client-select-input');
    if (!input || !input.value) return;

    const val = input.value;
    let selectedQboId = '';
    let selectedEngId = '0';

    // Parse options from data-value if matched in datalist
    const datalist = document.getElementById('client-select-options');
    if (datalist) {
        const options = datalist.querySelectorAll('option');
        for (const opt of options) {
            if (opt.value === val) {
                const dataVal = opt.getAttribute('data-value');
                if (dataVal) {
                    const parts = dataVal.split(':');
                    selectedQboId = parts[0];
                    selectedEngId = parts[1];
                }
                break;
            }
        }
    }

    if (!selectedQboId && window.clientData) {
        for (const k in window.clientData) {
            if (k === val || window.clientData[k].id === val) {
                selectedQboId = window.clientData[k].id;
                break;
            }
        }
    }

    if (!selectedQboId) return;

    // Load Client Data into Workspace
    let clientObj = null;
    for (const k in window.clientData) {
        if (window.clientData[k].id === selectedQboId) {
            clientObj = window.clientData[k];
            break;
        }
    }

    if (!clientObj) return;

    const serviceTable = document.getElementById('service-table');
    const actionsContainer = document.getElementById('actions-container');
    const oosContainer = document.getElementById('out-of-scope-container');
    const submitBtn = document.getElementById('btn-submit-main');
    const lockBanner = document.getElementById('lock-banner-container');
    const syncToolbar = document.getElementById('qbo-sync-toolbar-container');

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

    if (lockBanner) {
        if (draft && draft.is_locked) {
            lockBanner.style.display = 'block';
            lockBanner.innerHTML = `<div style="background:#fff3cd; border:1px solid #ffebaa; color:#856404; padding:12px; margin-bottom:15px; border-radius:4px;">🔒 <strong>Engagement #${selectedEngId} is locked.</strong> Sourced on ${draft.locked_mtime}.</div>`;
        } else {
            lockBanner.style.display = 'none';
        }
    }

    // Populate rows
    if (window.reconstructedRows && window.reconstructedRows.length > 0) {
        window.reconstructedRows.forEach(r => addServiceRow(r.item_id, r.service, r.fee, r.notes));
        window.reconstructedRows = []; // Clear once consumed
    } else if (draft && draft.rows && draft.rows.length > 0) {
        draft.rows.forEach(r => addServiceRow(r.item_id, r.service, r.fee, r.notes));
    } else {
        // Fallback default row
        addServiceRow();
    }

    if (submitBtn) {
        submitBtn.style.display = 'inline-block';
        submitBtn.innerText = '⚡ Generate Document Preview & Execute Pipeline';
    }

    recalculateTotals();
}

function addServiceRow(itemId = '', service = '', fee = '', notes = '') {
    const tbody = document.getElementById('service-tbody');
    if (!tbody) return;

    const rowId = Date.now() + Math.floor(Math.random() * 1000);
    const tr = document.createElement('tr');
    tr.id = `service_row_${rowId}`;

    let optionsHtml = '<option value="">-- Select Service Item --</option>';
    if (window.clientData) {
        const sampleClient = Object.values(window.clientData)[0];
        if (sampleClient && sampleClient.exposed_services) {
            sampleClient.exposed_services.forEach(s => {
                const sel = String(s.id) === String(itemId) ? 'selected' : '';
                optionsHtml += `<option value="${s.id}" data-fee="${s.fee}" data-notes="${escapeHtml(s.notes)}" ${sel}>${escapeHtml(s.name)} ($${s.fee})</option>`;
            });
        }
    }

    tr.innerHTML = `
        <td style="text-align:center;">
            <button type="button" class="btn-remove-row" onclick="removeServiceRow('${rowId}')" title="Remove Line Item">×</button>
            <input type="hidden" name="selected_rows" value="${rowId}">
            <input type="hidden" name="row_item_id_${rowId}" id="row_item_id_${rowId}" value="${itemId}">
        </td>
        <td>
            <select name="row_service_${rowId}" id="row_service_${rowId}" style="width:100%; padding:8px;" onchange="onServiceDropdownChange('${rowId}')">
                ${optionsHtml}
            </select>
        </td>
        <td>
            <input type="number" name="row_fee_${rowId}" id="row_fee_${rowId}" value="${fee}" placeholder="0" style="width:100%; padding:8px; text-align:right;" oninput="recalculateTotals()">
        </td>
        <td>
            <input type="text" name="row_notes_${rowId}" id="row_notes_${rowId}" value="${escapeHtml(notes)}" placeholder="Scope notes or specifications..." style="width:100%; padding:8px;">
        </td>
    `;

    tbody.appendChild(tr);
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
        if (feeInput && (!feeInput.value || feeInput.value === '0')) {
            feeInput.value = opt.getAttribute('data-fee') || '0';
        }
        if (notesInput && !notesInput.value) {
            notesInput.value = opt.getAttribute('data-notes') || '';
        }
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
            const text = select ? select.options[select.selectedIndex]?.text.toLowerCase() || '' : '';
            if (text.includes('discount') || text.includes('referral')) {
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
        if (window.clientData[k].id === qboId) {
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
        const qboId = client.id;
        const meta = client.metadata || {};
        const clientAddr = client.address || {};
        const engagements = client.engagements || {};

        Object.keys(engagements).forEach(engId => {
            const draft = engagements[engId];
            const isLocked = Boolean(draft.is_locked);
            const isPaper = (draft.delivery_format === 'paper' || meta.delivery_format === 'paper');

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

            const entityType = draft.entity_type || meta.entity_type || 'individual';
            const engTitle = draft.engagement_title || `Engagement #${engId}`;

            const coSignerEmailVal = coSigner.email || draft.co_signer_email || meta.co_signer_email || '';
            const coSignerNameVal = coSigner.name || draft.co_signer_name || meta.co_signer_name || '';
            const isDualSigner = (coSignerEmailVal.includes('@') || coSignerNameVal.length > 0);
            const clientNameClean = pSigner.friendly_name || draft.friendly_name || meta.friendly_name || clientKey.split(' (Customer')[0];

            const searchableText = `${qboId} ${clientNameClean} ${engTitle} ${entityType} ${clientFee}`.toLowerCase();

            const matchesSearch = searchableText.includes(searchQuery);
            let matchesFormat = true;
            if (formatFilter === 'paper') matchesFormat = isPaper;
            if (formatFilter === 'electronic') matchesFormat = !isPaper;

            if (matchesSearch && matchesFormat) {
                allRecords.push({
                    qboId, engId, clientKey, client, draft, isLocked, isPaper,
                    clientFee, entityType, isDualSigner, coSignerNameVal, coSignerEmailVal,
                    isDataIncomplete, clientNameClean, engTitle
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
                case 7: valA = a.isLocked ? 2 : (a.isDataIncomplete ? 0 : 1); valB = b.isLocked ? 2 : (b.isDataIncomplete ? 0 : 1); break;
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
            globalBatchSelections[key] = (!item.isLocked && !item.isDataIncomplete);
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
        const { qboId, engId, isLocked, isPaper, clientFee, entityType, isDualSigner, coSignerNameVal, coSignerEmailVal, isDataIncomplete, clientNameClean, engTitle } = item;
        const selectionKey = `${qboId}:${engId}`;
        const isChecked = Boolean(globalBatchSelections[selectionKey]);

        let statusBadge = '<span class="badge badge-electronic">Ready</span>';
        let checkboxDisabled = '';

        if (isLocked) {
            statusBadge = '<span class="badge badge-locked">🔒 Sent</span>';
            checkboxDisabled = 'disabled';
        } else if (isDataIncomplete) {
            statusBadge = '<span class="badge badge-warning">⚠️ Data Incomplete</span>';
            checkboxDisabled = 'disabled';
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

        const tr = document.createElement('tr');
        tr.id = `batch_row_${qboId}_${engId}`;
        tr.className = `batch-row-item format-${isPaper ? 'paper' : 'electronic'}`;
        tr.innerHTML = `
            <td style="text-align: center;">
                <input type="checkbox" class="batch-checkbox" data-qbo-id="${qboId}" data-eng-id="${engId}" ${checkboxDisabled} ${checkedAttr} onchange="handleBatchCheckboxToggle('${qboId}', '${engId}', this.checked)">
            </td>
            <td style="font-family: monospace; font-size: 12px; color: #555;">${qboId}</td>
            <td>
                <strong>${escapeHtml(clientNameClean)}</strong>
                <br/><small style="color: #0078d4; font-weight: 600;">${escapeHtml(engTitle)}</small>
            </td>
            <td><span class="badge ${entityType === 'individual' ? 'badge-individual' : 'badge-organization'}">${escapeHtml(entityType)}</span></td>
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
    let readyCount = 0;
    let incompleteCount = 0;
    let sentCount = 0;

    Object.keys(window.clientData).forEach(clientKey => {
        const client = window.clientData[clientKey];
        const qboId = client.id;
        const meta = client.metadata || {};
        const clientAddr = client.address || {};
        const engagements = client.engagements || {};

        Object.keys(engagements).forEach(engId => {
            const draft = engagements[engId];
            const isLocked = Boolean(draft.is_locked);
            const isPaper = (draft.delivery_format === 'paper' || meta.delivery_format === 'paper');

            const pSigner = draft.primary_signer || {};
            const addrObj = draft.billing_address || clientAddr;

            const hasServiceRows = Boolean(draft.rows && Array.isArray(draft.rows) && draft.rows.length > 0);
            const isAddressMissing = !addrObj.street || !addrObj.city;
            const isConfigMissing = !draft.entity_type && !meta.entity_type;
            const isEmailMissing = !pSigner.email && !draft.primary_signer_email && !client.email;
            const isDataIncomplete = !hasServiceRows || isAddressMissing || isConfigMissing || isEmailMissing;

            const selectionKey = `${qboId}:${engId}`;
            const isChecked = Boolean(globalBatchSelections[selectionKey]);

            if (isChecked) {
                selectedCount++;
                if (isPaper) selectedPaper++; else selectedElectronic++;
            }

            if (isLocked) {
                sentCount++;
            } else if (isDataIncomplete) {
                incompleteCount++;
            } else {
                readyCount++;
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
                <span class="strip-label">Ready to Dispatch:</span>
                <span class="strip-value text-green">${readyCount}</span>
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
        if (!item.isLocked && !item.isDataIncomplete) {
            globalBatchSelections[`${item.qboId}:${item.engId}`] = shouldSelect;
        }
    });
    renderBatchTableGrid();
}

function toggleClientDeliveryFormat(qboId, engId) {
    let targetDraft = null;
    for (const k in window.clientData) {
        if (window.clientData[k].id === qboId) {
            targetDraft = window.clientData[k].engagements?.[engId];
            break;
        }
    }

    if (!targetDraft || targetDraft.is_locked) return;

    const currentFmt = targetDraft.delivery_format || 'electronic';
    const newFmt = (currentFmt === 'paper') ? 'electronic' : 'paper';
    targetDraft.delivery_format = newFmt;

    // Send async save call to update format on server
    const params = new URLSearchParams();
    params.append('action', 'save_draft_only');
    params.append('client_name', qboId);
    params.append('engagement_id', engId);
    params.append('delivery_format', newFmt);

    fetch(window.location.href, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: params.toString()
    }).catch(err => console.error('Error toggling format:', err));

    renderBatchTableGrid();
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
        if (window.clientData[k].id === qboId) {
            clientObj = window.clientData[k];
            clientKeyName = k;
            break;
        }
    }

    if (!clientObj) return;

    const draft = clientObj.engagements?.[engId] || {};
    const titleEl = document.getElementById('modal-client-title');
    if (titleEl) {
        titleEl.innerText = `Edit: ${clientKeyName.split(' (Customer')[0]} (#${engId})`;
    }

    // Set temporary modal context attributes
    container.setAttribute('data-qbo-id', qboId);
    container.setAttribute('data-eng-id', engId);

    // Simple modal workspace content
    container.innerHTML = `
        <p style="font-size:13px; color:#555;">Modify profile settings and line items below. Changes autosave to draft disk memory.</p>
    `;

    modal.style.display = 'flex';
}

function closeBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    const container = document.getElementById('modal-workspace-container');
    if (modal) modal.style.display = 'none';

    if (container) {
        const qboId = container.getAttribute('data-qbo-id');
        const engId = container.getAttribute('data-eng-id');
        if (qboId && engId) {
            globalBatchSelections[`${qboId}:${engId}`] = true;
        }
    }
    renderBatchTableGrid();
}

function cancelBatchEditModal() {
    const modal = document.getElementById('batch-edit-modal');
    if (modal) modal.style.display = 'none';
}

function applyBatchBulkClonedScope() {
    const sourceVal = document.getElementById('batch-bulk-source-input')?.value || '';
    if (!sourceVal) return alert('Please select a source engagement to copy scope from.');

    const targetKeys = Object.keys(globalBatchSelections).filter(k => globalBatchSelections[k] === true);
    if (targetKeys.length === 0) return alert('No batch engagements selected.');

    const parts = sourceVal.split(':');
    if (parts.length < 2) return alert('Invalid source engagement selection.');

    const sourceQboId = parts[0];
    const sourceEngId = parts[1];

    let sourceDraft = null;
    for (const k in window.clientData) {
        if (window.clientData[k].id === sourceQboId) {
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
            if (window.clientData[k].id === qboId) {
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

function executeBatchPipelineSubmission() {
    const targetKeys = Object.keys(globalBatchSelections).filter(k => globalBatchSelections[k] === true);
    if (targetKeys.length === 0) return alert('No valid engagements selected.');

    if (!confirm(`Are you sure you want to process and dispatch ${targetKeys.length} client engagement(s)?`)) return;

    const overlay = document.getElementById('batch-progress-overlay');
    const terminalLog = document.getElementById('batch-terminal-log');
    const progressBar = document.getElementById('batch-progress-fill');
    const closeBtn = document.getElementById('btn-close-progress');

    if (overlay) overlay.style.display = 'flex';
    if (closeBtn) closeBtn.style.display = 'none';
    if (terminalLog) terminalLog.innerHTML = `Starting batch process for ${targetKeys.length} engagement(s)...\n`;

    let completed = 0;

    targetKeys.forEach(key => {
        const [qboId, engId] = key.split(':');
        completed++;
        if (progressBar) progressBar.style.width = `${(completed / targetKeys.length) * 100}%`;
        if (terminalLog) terminalLog.innerHTML += `\n[${completed}/${targetKeys.length}] Processing QBO ID ${qboId} / Eng ${engId}...`;
    });

    if (terminalLog) terminalLog.innerHTML += `\n\n========================================\nBatch pipeline execution complete!`;
    if (closeBtn) closeBtn.style.display = 'inline-block';
}
