/* ==========================================================================
   TARRANT ADVISORS — CLIENT INTAKE & PROFILE HUB JS
   ========================================================================== */

let customerCatalog = {};
let currentMode = "lead"; // Default mode: "lead" (New Lead)

// Environment detection
const urlParams = new URLSearchParams(window.location.search);
const isSandbox = urlParams.get("sandbox") === "true";
const CGI_SUFFIX = isSandbox ? "?sandbox=true" : "";

const LOOKUP_CGI_URL = `/cgi/intake_lookup.cgi${CGI_SUFFIX}`;
const PROVISION_CGI_URL = `/cgi/intake_provision.cgi${CGI_SUFFIX}`;

document.addEventListener("DOMContentLoaded", () => {
    // Set default contact date to today
    const contactDateInput = document.getElementById("contact_date");
    if (contactDateInput && !contactDateInput.value) {
        contactDateInput.value = new Date().toISOString().split("T")[0];
    }

    // Initialize mode setup
    setMode("lead");

    // Fetch existing QBO customers on load
    loadCustomerCatalog();
});

/**
 * Fetch QBO customer catalog from intake_lookup.py via CGI
 */
async function loadCustomerCatalog() {
    try {
        const response = await fetch(LOOKUP_CGI_URL, { method: "GET" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const data = await response.json();
        if (data.status === "success" && data.customers) {
            customerCatalog = data.customers;
            populateDatalist();
        } else {
            console.warn("Could not load customer catalog:", data.message);
        }
    } catch (err) {
        console.error("Error fetching QBO catalog:", err);
    }
}

/**
 * Populate datalist options for client lookup
 */
function populateDatalist() {
    const datalist = document.getElementById("client-select-options");
    if (!datalist) return;
    
    datalist.innerHTML = "";
    Object.keys(customerCatalog).sort().forEach(catalogKey => {
        const option = document.createElement("option");
        option.value = catalogKey;
        datalist.appendChild(option);
    });
}

/**
 * Switch mode between "lead" (New Lead) and "heal" (Existing QBO Client)
 * Clears and resets all input fields upon tab transition.
 */
function setMode(mode) {
    currentMode = mode;
    
    const btnLead = document.getElementById("btn-mode-lead");
    const btnHeal = document.getElementById("btn-mode-heal");
    const submitBtn = document.getElementById("btn-submit");
    const clientInput = document.getElementById("client-select-input");
    const notesSection = document.getElementById("section-notes");
    const formSections = document.querySelectorAll(".form-section");
    const badge = document.getElementById("client-lead-badge");
    const formEl = document.getElementById("intake-form");

    // 1. Reset form fields to clean state on mode switch
    if (formEl) {
        formEl.reset();
    }
    clearClientFields();

    // Re-apply today's date following form reset
    const contactDateInput = document.getElementById("contact_date");
    if (contactDateInput) {
        contactDateInput.value = new Date().toISOString().split("T")[0];
    }

    // 2. Adjust tab-specific styling & properties
    if (mode === "heal") {
        if (btnHeal) btnHeal.classList.add("active");
        if (btnLead) btnLead.classList.remove("active");
        
        if (notesSection) notesSection.classList.add("hidden");

        formSections.forEach(section => section.classList.add("heal-mode"));

        // Update Badge for Heal Mode
        if (badge) {
            badge.textContent = "Existing Client";
            badge.className = "badge-status heal";
        }

        if (submitBtn) {
            submitBtn.className = "btn-submit heal-mode";
            submitBtn.innerHTML = "💾 Update QBO Record";
        }

        if (clientInput) {
            clientInput.setAttribute("list", "client-select-options");
            clientInput.placeholder = "Select or search QBO client...";
        }
    } else {
        if (btnLead) btnLead.classList.add("active");
        if (btnHeal) btnHeal.classList.remove("active");
        
        if (notesSection) notesSection.classList.remove("hidden");

        formSections.forEach(section => section.classList.remove("heal-mode"));

        // Update Badge for Lead Mode
        if (badge) {
            badge.textContent = "New Client";
            badge.className = "badge-status lead";
        }

        if (submitBtn) {
            submitBtn.className = "btn-submit";
            submitBtn.innerHTML = "⚡ Provision New Client & Folders";
        }

        if (clientInput) {
            clientInput.removeAttribute("list");
            clientInput.placeholder = "Enter new lead name...";
        }
    }
}

/**
 * Handle typing/selecting in the Client Name input
 */
function onClientSearchInput() {
    const inputEl = document.getElementById("client-select-input");
    if (!inputEl) return;

    const inputVal = inputEl.value.trim();
    const qboIdInput = document.getElementById("qbo_id");
    
    // 1. If user selected a full datalist option like "Sper, Karyn (ID: 55)"
    if (customerCatalog[inputVal]) {
        if (currentMode !== "heal") {
            setMode("heal");
        }
        fillClientFields(customerCatalog[inputVal], inputVal);
        return;
    } 

    // 2. If the user completely cleared the input box, reset all client fields
    if (inputVal === "") {
        clearClientFields();
        return;
    }

    // 3. EDITING / TYPO CORRECTION:
    // Keep qbo_id attached as long as (ID: XX) matching the ID remains in the box
    if (qboIdInput && qboIdInput.value) {
        const idPattern = new RegExp(`\\(ID:\\s*${qboIdInput.value}\\)`, "i");
        if (!idPattern.test(inputVal)) {
            qboIdInput.value = ""; // Detach only if (ID: XX) was deleted or altered
        }
    }
}

/**
 * Auto-populate form fields from selected QBO customer metadata and preserve QBO ID
 */
function fillClientFields(clientData, catalogKey = "") {
    if (!clientData) return;

    const meta = clientData.metadata || {};
    const addr = clientData.address || {};

    let formEl = document.getElementById("intake-form");
    let qboIdInput = document.getElementById("qbo_id");
    if (!qboIdInput) {
        qboIdInput = document.createElement("input");
        qboIdInput.type = "hidden";
        qboIdInput.id = "qbo_id";
        qboIdInput.name = "qbo_id";
        if (formEl) formEl.appendChild(qboIdInput);
    }
    
    qboIdInput.value = clientData.id || "";
    qboIdInput.dataset.cleanName = clientData.display_name || "";

    const clientInput = document.getElementById("client-select-input");
    if (clientInput) {
        clientInput.value = catalogKey || `${clientData.display_name} (ID: ${clientData.id})`;
    }

    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el && val !== undefined && val !== null) el.value = val;
    };

    setVal("friendly_name", meta.friendly_name || clientData.display_name || "");
    setVal("primary_email", clientData.email || "");
    setVal("phone_number", clientData.phone || "");
    setVal("entity_type", meta.entity_type || "");
    setVal("co_signer_name", meta.co_signer_name || "");
    setVal("co_signer_email", meta.co_signer_email || "");

    // Address fields
    setVal("street", addr.street || "");
    setVal("city", addr.city || "");
    setVal("state", addr.state || "");
    setVal("zip", addr.zip || "");
}

/**
 * Clear auto-filled fields and purge hidden metadata
 */
function clearClientFields() {
    const qboIdInput = document.getElementById("qbo_id");
    if (qboIdInput) {
        qboIdInput.value = "";
        qboIdInput.dataset.cleanName = "";
    }

    const setVal = (id, val = "") => {
        const el = document.getElementById(id);
        if (el) el.value = val;
    };

    setVal("friendly_name");
    setVal("primary_email");
    setVal("phone_number");
    setVal("responder");
    setVal("entity_type");
    setVal("co_signer_name");
    setVal("co_signer_email");
    setVal("street");
    setVal("city");
    setVal("state");
    setVal("zip");
    setVal("notes");
}

/**
 * Close status overlay and optionally reset form
 */
function closeStatusOverlay(shouldReset = false) {
    const overlay = document.getElementById("status-overlay");
    if (overlay) overlay.style.display = "none";

    if (shouldReset) {
        setMode("lead");
        loadCustomerCatalog(); // Refresh catalog in background
    }
}

/**
 * Handle form submission via POST
 */
async function handleFormSubmit(event) {
    event.preventDefault();

    const overlay = document.getElementById("status-overlay");
    const statusTitle = document.getElementById("status-title");
    const statusText = document.getElementById("status-text");
    const statusSpinner = document.getElementById("status-spinner");
    const btnClose = document.getElementById("btn-close-overlay");

    if (overlay) overlay.style.display = "flex";
    if (statusSpinner) statusSpinner.style.display = "block";
    if (btnClose) btnClose.style.display = "none";

    const isNewLead = (currentMode === "lead");

    if (statusTitle) {
        statusTitle.textContent = isNewLead ? "Provisioning New Client..." : "Updating QBO Profile...";
    }
    if (statusText) {
        statusText.textContent = isNewLead 
            ? "Creating QBO Customer record, generating SharePoint folder trees, copying log files, and sending team notifications..."
            : "Syncing updated metadata to QuickBooks Online and sending email notification...";
    }

    const formData = new FormData(event.target);
    const payload = {};

    for (let [key, value] of formData.entries()) {
        let cleanVal = value;
        
        // Strip "(ID: 123)" if present in client_name
        if (key === "client_name") {
            cleanVal = value.replace(/\s*\(\s*ID:\s*\d+\s*\)/gi, "").trim();
        }
        
        payload[key] = cleanVal;
    }

    payload["is_new_lead"] = isNewLead ? "true" : "false";

    try {
        const response = await fetch(PROVISION_CGI_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error(`HTTP ${response.status} - Internal Server Error`);

        const result = await response.json();

        if (result.status === "success") {
            if (statusSpinner) statusSpinner.style.display = "none";
            if (statusTitle) {
                statusTitle.style.color = isNewLead ? "#15803d" : "#0369a1";
                statusTitle.textContent = isNewLead ? "✨ New Client Provisioned!" : "🟢 Profile Updated Successfully!";
            }
            if (statusText) {
                statusText.textContent = result.message || "Operation completed successfully.";
            }
            
            if (btnClose) {
                btnClose.textContent = "Done & Reset Form";
                btnClose.className = "btn-submit";
                btnClose.onclick = () => closeStatusOverlay(true);
                btnClose.style.display = "inline-block";
            }
        } else {
            throw new Error(result.message || "An error occurred during processing.");
        }
    } catch (err) {
        if (statusSpinner) statusSpinner.style.display = "none";
        if (statusTitle) {
            statusTitle.style.color = "#d9381e";
            statusTitle.textContent = "❌ Process Failed";
        }
        if (statusText) {
            statusText.textContent = err.message || "Could not complete the intake request. Please check the server logs.";
        }
        
        if (btnClose) {
            btnClose.textContent = "Close & Keep Editing";
            btnClose.className = "btn-submit heal-mode";
            btnClose.onclick = () => closeStatusOverlay(false);
            btnClose.style.display = "inline-block";
        }
    }
}
