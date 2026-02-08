document.addEventListener('DOMContentLoaded', () => {
    const status = document.getElementById('form-status');
    const showStatus = (type, message) => {
        if (!status) return;
        status.className = `alert alert-${type}`;
        status.textContent = message;
        status.classList.remove('d-none');
        setTimeout(() => status.classList.add('d-none'), 4000);
    };

    const getCsrfToken = () => {
        const tokenField = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return tokenField ? tokenField.value : '';
    };

    const normalizeToArray = (value) => {
        if (Array.isArray(value)) return value;
        if (value == null) return [];
        if (typeof value === 'string') {
            const s = value.trim();
            if (!s) return [];
            try { return normalizeToArray(JSON.parse(s)); } catch (e) { return []; }
        }
        if (typeof value === 'object') {
            if (Array.isArray(value.results)) return value.results;
            if (Array.isArray(value.data)) return value.data;
            return Object.values(value).filter(v => v && typeof v === 'object');
        }
        return [];
    };

    const currencyFmt = (amount) => {
        const num = Number(amount || 0);
        return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num);
    };

    const escapeHtml = (value) => (
        String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
    );

    const formatLastSent = (rawIso) => {
        if (!rawIso) return '-';
        try {
            const dt = new Date(rawIso);
            if (Number.isNaN(dt.getTime())) return '-';
            const today = new Date();
            if (dt.getFullYear() === today.getFullYear() && dt.getMonth() === today.getMonth() && dt.getDate() === today.getDate()) {
                return 'Today';
            }
            return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: '2-digit' }).format(dt);
        } catch (e) {
            return '-';
        }
    };

    const formatShortDate = (rawIso) => {
        if (!rawIso) return '-';
        try {
            const dt = new Date(rawIso);
            if (Number.isNaN(dt.getTime())) return '-';
            return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: '2-digit' }).format(dt);
        } catch (e) {
            return '-';
        }
    };

    const formatDateTime = (rawIso) => {
        if (!rawIso) return '-';
        try {
            const dt = new Date(rawIso);
            if (Number.isNaN(dt.getTime())) return '-';
            return new Intl.DateTimeFormat('en-US', { month: 'short', day: '2-digit', hour: 'numeric', minute: '2-digit' }).format(dt);
        } catch (e) {
            return '-';
        }
    };

    const extractFirstError = (errors) => {
        if (!errors || typeof errors !== 'object') return null;
        if (errors.form) {
            const firstField = Object.keys(errors.form)[0];
            const firstError = errors.form[firstField]?.[0]?.message || errors.form[firstField]?.[0];
            if (firstError) return firstError;
        }
        const keys = Object.keys(errors);
        for (const key of keys) {
            const val = errors[key];
            if (Array.isArray(val) && val.length) {
                const first = val[0];
                if (first && typeof first === 'object' && 'message' in first) return first.message;
                return first;
            }
        }
        return null;
    };

    const dashboardModeButtons = Array.from(document.querySelectorAll('[data-dashboard-mode]'));
    const dashboardViews = Array.from(document.querySelectorAll('[data-dashboard-view]'));
    const DASHBOARD_MODE_STORAGE_KEY = 'parts-dashboard-mode';
    const DASHBOARD_MODE_HASHES = {
        pos: '#in-store-pos',
        online: '#online-store',
        returns: '#returns',
    };

    const normalizeDashboardMode = (value) => {
        const normalized = String(value || '').trim().toLowerCase();
        if (normalized === 'online') return 'online';
        if (normalized === 'returns' || normalized === 'return') return 'returns';
        return 'pos';
    };

    const dashboardModeFromHash = (hashValue) => {
        const hash = String(hashValue || '').trim().toLowerCase();
        if (!hash) return '';
        if (hash === '#online-store') return 'online';
        if (hash === '#returns' || hash === '#return-center' || hash === '#returns-center') return 'returns';
        if (hash === '#in-store-pos' || hash === '#pos') return 'pos';
        return '';
    };

    const syncDashboardModeHash = (mode) => {
        const hash = DASHBOARD_MODE_HASHES[normalizeDashboardMode(mode)] || DASHBOARD_MODE_HASHES.pos;
        const nextUrl = `${window.location.pathname}${window.location.search}${hash}`;
        window.history.replaceState(null, '', nextUrl);
    };

    const setDashboardMode = (mode, options = {}) => {
        const nextMode = normalizeDashboardMode(mode);
        const shouldPersist = options.persist !== false;
        const shouldSyncHash = options.syncHash !== false;
        dashboardModeButtons.forEach((btn) => {
            const active = btn.dataset.dashboardMode === nextMode;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        dashboardViews.forEach((view) => {
            const active = view.dataset.dashboardView === nextMode;
            view.classList.toggle('d-none', !active);
        });
        if (shouldPersist) {
            try {
                window.localStorage.setItem(DASHBOARD_MODE_STORAGE_KEY, nextMode);
            } catch (e) {
                // ignore storage errors
            }
        }
        if (shouldSyncHash) {
            syncDashboardModeHash(nextMode);
        }
        return nextMode;
    };

    if (dashboardModeButtons.length && dashboardViews.length) {
        dashboardModeButtons.forEach((btn) => {
            btn.addEventListener('click', () => setDashboardMode(btn.dataset.dashboardMode || 'pos'));
        });

        const modeFromUrl = new URLSearchParams(window.location.search).get('mode');
        const modeFromHash = dashboardModeFromHash(window.location.hash);
        let modeFromStorage = '';
        try {
            modeFromStorage = window.localStorage.getItem(DASHBOARD_MODE_STORAGE_KEY) || '';
        } catch (e) {
            modeFromStorage = '';
        }
        const defaultMode = dashboardViews.find(view => !view.classList.contains('d-none'))?.dataset.dashboardView || 'pos';
        setDashboardMode(modeFromUrl || modeFromHash || modeFromStorage || defaultMode, { syncHash: false });

        window.addEventListener('hashchange', () => {
            const nextMode = dashboardModeFromHash(window.location.hash);
            if (!nextMode) return;
            setDashboardMode(nextMode, { syncHash: false });
        });
    }

    // POS terminal (in-store sales)
    const posPanel = document.getElementById('pos-terminal');
    if (posPanel) {
        const posForm = document.getElementById('pos-checkout-form');
        posForm?.addEventListener('submit', (e) => e.preventDefault());

        let productsRaw = [];
        let customersRaw = [];
        let vehiclesRaw = [];
        let servicesRaw = [];
        try { productsRaw = JSON.parse(document.getElementById('parts-pos-products')?.textContent || '[]'); } catch (e) { productsRaw = []; }
        try { customersRaw = JSON.parse(document.getElementById('parts-pos-customers')?.textContent || '[]'); } catch (e) { customersRaw = []; }
        try { vehiclesRaw = JSON.parse(document.getElementById('parts-pos-vehicles')?.textContent || '[]'); } catch (e) { vehiclesRaw = []; }
        try { servicesRaw = JSON.parse(document.getElementById('parts-pos-services')?.textContent || '[]'); } catch (e) { servicesRaw = []; }

        const allProducts = normalizeToArray(productsRaw);
        const quickCustomers = normalizeToArray(customersRaw);
        const quickVehicles = normalizeToArray(vehiclesRaw);
        const quickServiceCatalog = normalizeToArray(servicesRaw);

        const posTaxRate = Number(posPanel.dataset.taxRate || 0);
        const posPaymentUrlTemplate = posPanel.dataset.paymentUrlTemplate || '';
        const posSendEmailUrlTemplate = posPanel.dataset.sendEmailUrlTemplate || '';
        const posSendPaidEmailUrlTemplate = posPanel.dataset.sendPaidEmailUrlTemplate || '';
        const posPrintUrlTemplate = posPanel.dataset.printUrlTemplate || '';
        const posPaidPrintUrlTemplate = posPanel.dataset.paidPrintUrlTemplate || '';
        const posAddCustomerUrl = posPanel.dataset.addCustomerUrl || '';
        const posAddVehicleUrl = posPanel.dataset.addVehicleUrl || '';
        const posReturnLookupUrl = posPanel.dataset.returnLookupUrl || '';
        const posReturnCreateUrl = posPanel.dataset.returnCreateUrl || '';
        const posCreditDetailUrlTemplate = posPanel.dataset.creditDetailUrlTemplate || '';

        const posSearchInput = document.getElementById('pos-search-input');
        const posSearchClear = document.getElementById('pos-search-clear');
        const posTabButtons = Array.from(document.querySelectorAll('[data-pos-tab]'));
        const posProductGrid = document.getElementById('pos-product-grid');
        const posServiceGrid = document.getElementById('pos-service-grid');
        const posCustomEntry = document.getElementById('pos-custom-entry');
        const posCustomName = document.getElementById('pos-custom-name');
        const posCustomQty = document.getElementById('pos-custom-qty');
        const posCustomRate = document.getElementById('pos-custom-rate');
        const posCustomAdd = document.getElementById('pos-custom-add');

        const posSaleDate = document.getElementById('pos-sale-date');
        const posEmail = document.getElementById('pos-email');

        const posCustomerIdInput = document.getElementById('pos-customer');
        const posCustomerPickerBtn = document.getElementById('pos-customer-picker');
        const posCustomerSearch = document.getElementById('pos-customer-search');
        const posCustomerList = document.getElementById('pos-customer-list');
        const posAddCustomerBtn = document.getElementById('pos-add-customer');

        const posVehicleIdInput = document.getElementById('pos-vehicle');
        const posVehiclePickerBtn = document.getElementById('pos-vehicle-picker');
        const posVehicleSearch = document.getElementById('pos-vehicle-search');
        const posVehicleList = document.getElementById('pos-vehicle-list');
        const posVehicleHint = document.getElementById('pos-vehicle-hint');
        const posAddVehicleBtn = document.getElementById('pos-add-vehicle');

        const posCartLines = document.getElementById('pos-cart-lines');
        const posSubtotalEl = document.getElementById('pos-subtotal');
        const posTaxEl = document.getElementById('pos-tax');
        const posTotalEl = document.getElementById('pos-total');
        const posTaxRateLabel = document.getElementById('pos-tax-rate-label');
        const posTaxExempt = document.getElementById('pos-tax-exempt');

        const posRecordPayment = document.getElementById('pos-record-payment');
        const posPaymentAmount = document.getElementById('pos-payment-amount');
        const posPayFull = document.getElementById('pos-pay-full');
        const posChangeDue = document.getElementById('pos-change-due');
        const posMethodsContainer = document.getElementById('pos-methods');
        const posMethodButtons = Array.from(document.querySelectorAll('#pos-methods .pos-method-btn'));
        const posPaymentIconBase = posMethodsContainer?.dataset.iconBase || '';

        const posClearCart = document.getElementById('pos-clear-cart');
        const posSaveSale = document.getElementById('pos-save-sale');
        const posCheckoutEmailBtn = document.getElementById('pos-checkout-email-btn');
        const posCheckoutPrintBtn = document.getElementById('pos-checkout-print-btn');
        const posCheckoutEmailPrintBtn = document.getElementById('pos-checkout-email-print-btn');
        const posCheckoutActionButtons = Array.from(document.querySelectorAll('.pos-btn-checkout'));
        const posCheckoutLabels = Array.from(document.querySelectorAll('.pos-checkout-label'));

        const posReturnModeButtons = Array.from(document.querySelectorAll('[data-pos-return-mode]'));
        const posReturnCustomer = document.getElementById('pos-return-customer');
        const posReturnInvoice = document.getElementById('pos-return-invoice');
        const posReturnDate = document.getElementById('pos-return-date');
        const posReturnMemo = document.getElementById('pos-return-memo');
        const posReturnReload = document.getElementById('pos-return-reload');
        const posReturnSubmit = document.getElementById('pos-return-submit');
        const posReturnLines = document.getElementById('pos-return-lines');
        const posReturnSummary = document.getElementById('pos-return-summary');
        const posReturnOpenCredit = document.getElementById('pos-return-open-credit');

        if (posTaxRateLabel) {
            const pct = Math.round(posTaxRate * 100);
            posTaxRateLabel.textContent = `${pct}%`;
        }

        let posCart = [];
        let posActiveTab = 'products';
        let posActiveMethod = posMethodButtons[0]?.dataset.method || 'Cash';
        let posPaymentAuto = true;
        let posReturnMode = 'core';
        let posReturnRows = [];

        const customerDisplay = (c) => {
            if (!c) return 'Select customer';
            const name = c.name || c.email || 'Customer';
            return c.email ? `${name} (${c.email})` : name;
        };

        const vehicleDisplay = (v) => {
            if (!v) return 'Select vehicle';
            const unit = v.unit_number ? `Unit ${v.unit_number}` : '';
            const makeModel = v.make_model || '';
            const plate = v.license_plate ? `(${v.license_plate})` : '';
            const vin = (v.vin || v.vin_number) ? `VIN ${v.vin || v.vin_number}` : '';
            return [unit, makeModel, plate, vin].filter(Boolean).join(' ').trim() || 'Vehicle';
        };

        const setPosPickerLabel = (btn, text) => {
            if (!btn) return;
            btn.textContent = text || 'Select';
        };

        const updatePosVehicleAddVisibility = () => {
            if (!posAddVehicleBtn || !posCustomerIdInput) return;
            const hasCustomer = !!posCustomerIdInput.value;
            posAddVehicleBtn.classList.toggle('d-none', !hasCustomer);
        };

        const renderPosCustomerList = () => {
            if (!posCustomerList) return;
            const q = (posCustomerSearch?.value || '').trim().toLowerCase();
            const items = (quickCustomers || []).filter(c => {
                const name = (c.name || '').toLowerCase();
                const email = (c.email || '').toLowerCase();
                return !q || name.includes(q) || email.includes(q);
            }).sort((a, b) => (a.name || a.email || '').localeCompare((b.name || b.email || ''), undefined, { sensitivity: 'base' }));

            const currentId = posCustomerIdInput?.value || '';
            const html = [
                `<button type="button" class="dropdown-item" data-pos-customer-id="">(Clear)</button>`,
                `<div class="dropdown-divider"></div>`,
                ...(items.length
                    ? items.map(c => {
                        const active = String(c.id) === String(currentId) ? ' active' : '';
                        return `<button type="button" class="dropdown-item${active}" data-pos-customer-id="${c.id}">${escapeHtml(customerDisplay(c))}</button>`;
                    })
                    : [`<div class="text-muted small px-2 py-1">No customers found.</div>`]
                )
            ].join('');
            posCustomerList.innerHTML = html;
        };

        const renderPosVehicleList = () => {
            if (!posVehicleList) return;
            const custId = posCustomerIdInput?.value || '';
            const q = (posVehicleSearch?.value || '').trim().toLowerCase();
            const currentId = posVehicleIdInput?.value || '';

            if (posVehicleHint) posVehicleHint.classList.toggle('d-none', !!custId);

            const items = (quickVehicles || [])
                .filter(v => custId && String(v.customer_id) === String(custId))
                .filter(v => {
                    if (!q) return true;
                    const hay = [
                        v.unit_number,
                        v.make_model,
                        v.license_plate,
                        v.vin,
                        v.vin_number,
                    ].map(x => (x || '').toString().toLowerCase()).join(' ');
                    return hay.includes(q);
                })
                .sort((a, b) => (vehicleDisplay(a)).localeCompare(vehicleDisplay(b), undefined, { sensitivity: 'base' }));

            const html = [
                `<button type="button" class="dropdown-item" data-pos-vehicle-id="">(Clear)</button>`,
                `<div class="dropdown-divider"></div>`,
                ...(custId
                    ? (items.length
                        ? items.map(v => {
                            const active = String(v.id) === String(currentId) ? ' active' : '';
                            return `<button type="button" class="dropdown-item${active}" data-pos-vehicle-id="${v.id}">${escapeHtml(vehicleDisplay(v))}</button>`;
                        })
                        : [`<div class="text-muted small px-2 py-1">No vehicles found for this customer.</div>`]
                    )
                    : [`<div class="text-muted small px-2 py-1">Select a customer first.</div>`]
                )
            ].join('');
            posVehicleList.innerHTML = html;
        };

        const posReturnTypeLabel = () => (posReturnMode === 'core' ? 'core' : 'product');
        const posReturnLineTypeLabel = (lineType) => {
            const normalized = String(lineType || '').toLowerCase();
            if (normalized === 'core_charge') return 'Core charge';
            if (normalized === 'product') return 'Product';
            return 'Return line';
        };
        const posReturnFormatQty = (value) => {
            const num = Number(value);
            if (!Number.isFinite(num)) return '0';
            const rounded = Math.round(num * 100) / 100;
            return Number.isInteger(rounded) ? String(rounded) : String(rounded);
        };

        const setPosReturnSummary = (message, isError = false) => {
            if (!posReturnSummary) return;
            posReturnSummary.textContent = message || '';
            posReturnSummary.style.color = isError ? '#b91c1c' : '';
        };

        const buildPosCreditDetailUrl = (creditId) => {
            if (!creditId || !posCreditDetailUrlTemplate) return '';
            if (posCreditDetailUrlTemplate.includes('/0/')) {
                return posCreditDetailUrlTemplate.replace('/0/', `/${creditId}/`);
            }
            return posCreditDetailUrlTemplate;
        };

        const renderPosReturnCustomerSelect = () => {
            if (!posReturnCustomer) return;
            const currentId = posReturnCustomer.value || '';
            const options = [
                '<option value="">Select customer</option>',
                ...(quickCustomers || [])
                    .slice()
                    .sort((a, b) => (a.name || a.email || '').localeCompare((b.name || b.email || ''), undefined, { sensitivity: 'base' }))
                    .map((customer) => `<option value="${escapeHtml(customer.id)}">${escapeHtml(customerDisplay(customer))}</option>`),
            ];
            posReturnCustomer.innerHTML = options.join('');
            if (currentId && (quickCustomers || []).some(c => String(c.id) === String(currentId))) {
                posReturnCustomer.value = currentId;
            }
        };

        const renderPosReturnInvoiceSelect = (preferredInvoiceId = '') => {
            if (!posReturnInvoice) return;
            const existingValue = preferredInvoiceId || posReturnInvoice.value || '';
            const invoiceMap = new Map();
            (posReturnRows || []).forEach((row) => {
                const invoiceId = String(row.invoice_id || '');
                if (!invoiceId || invoiceMap.has(invoiceId)) return;
                invoiceMap.set(invoiceId, {
                    id: invoiceId,
                    invoice_number: row.invoice_number || `Invoice ${invoiceId}`,
                    invoice_date: row.invoice_date || '',
                });
            });
            const options = [
                '<option value="">All invoices</option>',
                ...Array.from(invoiceMap.values()).map((invoice) => {
                    const dateText = invoice.invoice_date ? ` - ${formatShortDate(invoice.invoice_date)}` : '';
                    return `<option value="${escapeHtml(invoice.id)}">${escapeHtml(invoice.invoice_number)}${escapeHtml(dateText)}</option>`;
                }),
            ];
            posReturnInvoice.innerHTML = options.join('');
            posReturnInvoice.disabled = invoiceMap.size === 0;
            if (existingValue && invoiceMap.has(String(existingValue))) {
                posReturnInvoice.value = String(existingValue);
            } else {
                posReturnInvoice.value = '';
            }
        };

        const getVisiblePosReturnRows = () => {
            const selectedInvoiceId = posReturnInvoice?.value || '';
            if (!selectedInvoiceId) return posReturnRows || [];
            return (posReturnRows || []).filter(
                (row) => String(row.invoice_id || '') === String(selectedInvoiceId),
            );
        };

        const renderPosReturnRows = () => {
            if (!posReturnLines) return;

            if (!posReturnCustomer?.value) {
                posReturnLines.innerHTML = '<tr><td colspan="8" class="text-muted text-center py-3">Select a customer to load returnable lines.</td></tr>';
                setPosReturnSummary('Select a customer to load returnable lines.');
                return;
            }

            if (!posReturnRows.length) {
                posReturnLines.innerHTML = `<tr><td colspan="8" class="text-muted text-center py-3">No ${escapeHtml(posReturnTypeLabel())} return lines available.</td></tr>`;
                setPosReturnSummary(`No ${posReturnTypeLabel()} return lines available for this customer.`);
                return;
            }

            const visibleRows = getVisiblePosReturnRows();
            if (!visibleRows.length) {
                posReturnLines.innerHTML = '<tr><td colspan="8" class="text-muted text-center py-3">No lines match this invoice filter.</td></tr>';
                setPosReturnSummary('No lines match this invoice filter.');
                return;
            }

            posReturnLines.innerHTML = visibleRows.map((row) => {
                const soldQty = Number(row.sold_qty || 0);
                const returnedQty = Number(row.returned_qty || 0);
                const availableQty = Number(row.available_qty || 0);
                const safeAvailable = Number.isFinite(availableQty) && availableQty > 0 ? availableQty : 0;
                const description = row.description || 'Return line';
                const partNo = row.part_no || '-';
                const lineTypeLabel = posReturnLineTypeLabel(row.line_type);
                const imageUrl = typeof row.image_url === 'string' ? row.image_url.trim() : '';
                const imageHtml = imageUrl
                    ? `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(description)}" loading="lazy">`
                    : '<div class="pos-return-thumb-fallback"><i class="fa-solid fa-box-open"></i></div>';
                return `
                    <tr data-return-line-id="${row.source_invoice_item_id}">
                        <td>
                            <div class="fw-semibold">${escapeHtml(row.invoice_number || '')}</div>
                            <div class="text-muted">${escapeHtml(formatShortDate(row.invoice_date || ''))}</div>
                        </td>
                        <td>${escapeHtml(partNo)}</td>
                        <td>
                            <div class="pos-return-item">
                                <div class="pos-return-thumb">${imageHtml}</div>
                                <div>
                                    <div class="pos-return-item-title">${escapeHtml(description)}</div>
                                    <div class="pos-return-item-meta">${escapeHtml(lineTypeLabel)}</div>
                                </div>
                            </div>
                        </td>
                        <td class="text-end">${escapeHtml(posReturnFormatQty(soldQty))}</td>
                        <td class="text-end">${escapeHtml(posReturnFormatQty(returnedQty))}</td>
                        <td class="text-end">${escapeHtml(posReturnFormatQty(safeAvailable))}</td>
                        <td class="text-end">${escapeHtml(currencyFmt(row.price || 0))}</td>
                        <td class="text-end">
                            <div class="pos-return-qty-wrap">
                                <input
                                    type="number"
                                    class="pos-return-qty-input"
                                    min="0"
                                    step="0.01"
                                    max="${safeAvailable}"
                                    value=""
                                    data-return-source-id="${row.source_invoice_item_id}"
                                    data-return-available="${safeAvailable}"
                                >
                                <button
                                    type="button"
                                    class="pos-return-fill"
                                    data-return-fill-max="1"
                                    data-return-source-id="${row.source_invoice_item_id}">
                                    Max
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
            setPosReturnSummary(`${visibleRows.length} line(s) ready for ${posReturnTypeLabel()} returns.`);
        };

        const loadPosReturnLines = async ({ keepInvoiceSelection = true } = {}) => {
            if (!posReturnLookupUrl || !posReturnLines) return;
            const customerId = (posReturnCustomer?.value || '').trim();
            if (!customerId) {
                posReturnRows = [];
                renderPosReturnInvoiceSelect('');
                renderPosReturnRows();
                return;
            }

            const previousInvoice = keepInvoiceSelection ? (posReturnInvoice?.value || '') : '';
            posReturnLines.innerHTML = '<tr><td colspan="8" class="text-muted text-center py-3">Loading returnable lines...</td></tr>';
            setPosReturnSummary(`Loading ${posReturnTypeLabel()} return lines...`);

            const params = new URLSearchParams({
                customer_id: customerId,
                return_type: posReturnMode,
            });

            try {
                const resp = await fetch(`${posReturnLookupUrl}?${params.toString()}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Unable to load return lines.');
                }

                const rows = [];
                normalizeToArray(data.invoices).forEach((invoice) => {
                    normalizeToArray(invoice.items).forEach((item) => {
                        rows.push({
                            ...item,
                            invoice_id: invoice.id,
                            invoice_number: invoice.invoice_number,
                            invoice_date: invoice.date,
                        });
                    });
                });
                posReturnRows = rows;
                renderPosReturnInvoiceSelect(previousInvoice);
                renderPosReturnRows();
            } catch (err) {
                posReturnRows = [];
                renderPosReturnInvoiceSelect('');
                posReturnLines.innerHTML = '<tr><td colspan="8" class="text-danger text-center py-3">Unable to load return lines.</td></tr>';
                setPosReturnSummary(err.message || 'Unable to load return lines.', true);
            }
        };

        const setPosReturnMode = (mode) => {
            const normalized = String(mode || '').toLowerCase() === 'product' ? 'product' : 'core';
            posReturnMode = normalized;
            posReturnModeButtons.forEach((btn) => {
                const active = (btn.dataset.posReturnMode || '') === normalized;
                btn.classList.toggle('active', active);
                btn.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
            if (posReturnSubmit) {
                posReturnSubmit.innerHTML = normalized === 'core'
                    ? '<i class="fa-solid fa-rotate-left me-1"></i>Create Core Return'
                    : '<i class="fa-solid fa-rotate-left me-1"></i>Create Product Return';
            }
        };

        const collectPosReturnSelections = () => {
            if (!posReturnLines) return [];
            const selected = [];
            const seen = new Set();
            const qtyInputs = Array.from(posReturnLines.querySelectorAll('.pos-return-qty-input'));
            for (const input of qtyInputs) {
                const sourceId = Number(input.dataset.returnSourceId || 0);
                if (!Number.isFinite(sourceId) || sourceId <= 0) continue;
                const available = Number(input.dataset.returnAvailable || 0);
                const qty = Number(input.value || 0);
                if (!Number.isFinite(qty) || qty < 0) {
                    throw new Error('Return quantity must be a valid number.');
                }
                if (qty <= 0) continue;
                if (qty > available + 0.000001) {
                    throw new Error('Return quantity cannot exceed available quantity.');
                }
                if (seen.has(sourceId)) continue;
                seen.add(sourceId);
                selected.push({
                    source_invoice_item_id: sourceId,
                    qty: Number((Math.round(qty * 100) / 100).toFixed(2)),
                });
            }
            return selected;
        };

        const submitPosReturn = async () => {
            if (!posReturnCreateUrl) {
                showStatus('danger', 'Return endpoint is not configured.');
                return;
            }
            const customerId = (posReturnCustomer?.value || '').trim();
            if (!customerId) {
                showStatus('danger', 'Select a customer to process a return.');
                return;
            }

            let selections = [];
            try {
                selections = collectPosReturnSelections();
            } catch (err) {
                showStatus('danger', err.message || 'Please review return quantities.');
                return;
            }
            if (!selections.length) {
                showStatus('danger', 'Enter return quantity for at least one line.');
                return;
            }

            if (posReturnSubmit) posReturnSubmit.disabled = true;
            try {
                const payload = new FormData();
                payload.append('csrfmiddlewaretoken', getCsrfToken());
                payload.append('customer_id', customerId);
                payload.append('return_type', posReturnMode);
                if (posReturnDate?.value) payload.append('date', posReturnDate.value);
                if ((posReturnMemo?.value || '').trim()) payload.append('memo', posReturnMemo.value.trim());
                payload.append('line_items', JSON.stringify(selections));

                const resp = await fetch(posReturnCreateUrl, {
                    method: 'POST',
                    body: payload,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    throw new Error(data.error || 'Unable to create return credit.');
                }

                const creditNo = data.credit_no || data.credit_id || '';
                showStatus('success', `Return credit ${creditNo} created successfully.`);
                if (posReturnOpenCredit?.checked) {
                    const detailUrl = data.detail_url || buildPosCreditDetailUrl(data.credit_id);
                    if (detailUrl) {
                        window.open(detailUrl, '_blank', 'noopener');
                    }
                }
                if (posReturnMemo) posReturnMemo.value = '';
                await loadPosReturnLines({ keepInvoiceSelection: true });
            } catch (err) {
                showStatus('danger', err.message || 'Unable to process return.');
            } finally {
                if (posReturnSubmit) posReturnSubmit.disabled = false;
            }
        };

        const selectPosCustomer = (customerId) => {
            const id = (customerId || '').toString();
            if (posCustomerIdInput) posCustomerIdInput.value = id;

            const match = (quickCustomers || []).find(c => String(c.id) === String(id));
            setPosPickerLabel(posCustomerPickerBtn, match ? customerDisplay(match) : 'Select customer');
            if (posEmail && match && match.email) posEmail.value = match.email;

            if (posVehicleIdInput) posVehicleIdInput.value = '';
            setPosPickerLabel(posVehiclePickerBtn, 'Select vehicle');
            if (posVehicleSearch) posVehicleSearch.value = '';

            updatePosVehicleAddVisibility();
            renderPosCustomerList();
            renderPosVehicleList();

            if (posReturnCustomer) {
                renderPosReturnCustomerSelect();
                posReturnCustomer.value = id;
                loadPosReturnLines({ keepInvoiceSelection: false });
            }
        };

        const selectPosVehicle = (vehicleId) => {
            const id = (vehicleId || '').toString();
            if (posVehicleIdInput) posVehicleIdInput.value = id;
            const match = (quickVehicles || []).find(v => String(v.id) === String(id));
            setPosPickerLabel(posVehiclePickerBtn, match ? vehicleDisplay(match) : 'Select vehicle');
            renderPosVehicleList();
        };

        posCustomerSearch?.addEventListener('input', renderPosCustomerList);
        posCustomerList?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-pos-customer-id]');
            if (!btn) return;
            selectPosCustomer(btn.dataset.posCustomerId || '');
        });

        posVehicleSearch?.addEventListener('input', renderPosVehicleList);
        posVehicleList?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-pos-vehicle-id]');
            if (!btn) return;
            selectPosVehicle(btn.dataset.posVehicleId || '');
        });

        posReturnModeButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.posReturnMode || 'core';
                setPosReturnMode(mode);
                if (posReturnCustomer?.value) {
                    loadPosReturnLines({ keepInvoiceSelection: false });
                } else {
                    renderPosReturnRows();
                }
            });
        });

        posReturnCustomer?.addEventListener('change', () => {
            const selectedCustomerId = (posReturnCustomer.value || '').trim();
            if (selectedCustomerId && String(posCustomerIdInput?.value || '') !== selectedCustomerId) {
                selectPosCustomer(selectedCustomerId);
                return;
            }
            loadPosReturnLines({ keepInvoiceSelection: false });
        });

        posReturnInvoice?.addEventListener('change', renderPosReturnRows);
        posReturnReload?.addEventListener('click', () => loadPosReturnLines({ keepInvoiceSelection: true }));
        posReturnSubmit?.addEventListener('click', submitPosReturn);

        posReturnLines?.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-return-fill-max]');
            if (!btn) return;
            const sourceId = btn.dataset.returnSourceId || '';
            const input = posReturnLines.querySelector(`.pos-return-qty-input[data-return-source-id="${sourceId}"]`);
            if (!input) return;
            const maxValue = Number(input.dataset.returnAvailable || 0);
            if (!Number.isFinite(maxValue) || maxValue <= 0) return;
            input.value = String(maxValue);
        });

        posReturnLines?.addEventListener('input', (e) => {
            const input = e.target.closest('.pos-return-qty-input');
            if (!input) return;
            const value = Number(input.value || 0);
            const maxValue = Number(input.dataset.returnAvailable || 0);
            if (!Number.isFinite(value) || value < 0) {
                input.value = '';
                return;
            }
            if (Number.isFinite(maxValue) && value > maxValue) {
                input.value = String(maxValue);
            }
        });

        renderPosCustomerList();
        renderPosVehicleList();
        updatePosVehicleAddVisibility();
        renderPosReturnCustomerSelect();
        setPosReturnMode(posReturnMode);
        renderPosReturnInvoiceSelect('');
        renderPosReturnRows();

        const setPosTab = (tab) => {
            posActiveTab = tab;
            posTabButtons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.posTab === tab);
            });
            posProductGrid?.classList.toggle('d-none', tab !== 'products');
            posServiceGrid?.classList.toggle('d-none', tab !== 'services');
            posCustomEntry?.classList.toggle('d-none', tab !== 'custom');
            if (tab === 'products') renderPosProducts();
            if (tab === 'services') renderPosServices();
        };

        const formatLineTotal = (qty, rate) => currencyFmt((Number(qty) || 0) * (Number(rate) || 0));

        const posPriceForProduct = (p) => {
            const candidate = (p.sale_price !== null && p.sale_price !== undefined && p.sale_price !== '')
                ? Number(p.sale_price)
                : Number(p.cost_price || 0);
            return Number.isFinite(candidate) ? candidate : 0;
        };

        const posFormatQty = (value) => {
            const num = Number(value);
            if (!Number.isFinite(num)) return '0';
            const rounded = Math.round(num * 100) / 100;
            if (Number.isInteger(rounded)) return String(rounded);
            return String(rounded);
        };

        const normalizePaymentMethodKey = (value) => String(value || '')
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '');

        const paymentMethodLogoCdnBase = 'https://cdn.simpleicons.org';

        const paymentMethodIconMap = {
            cash: 'cash.svg',
            creditcard: 'credit-card.svg',
            debit: 'debit.svg',
            etransfer: 'e-transfer.svg',
            ach: 'ach.svg',
            cheque: 'cheque.svg',
            check: 'cheque.svg',
            manual: 'manual.svg',
            other: 'other.svg',
        };

        const paymentMethodLogoMap = {
            creditcard: ['visa'],
            debit: ['mastercard'],
            etransfer: ['zelle'],
            ach: ['swift'],
            other: ['paypal'],
        };

        const paymentMethodFaFallbackMap = {
            cash: 'fa-solid fa-money-bill-wave',
            creditcard: 'fa-regular fa-credit-card',
            debit: 'fa-regular fa-credit-card',
            etransfer: 'fa-solid fa-money-bill-transfer',
            ach: 'fa-solid fa-building-columns',
            cheque: 'fa-solid fa-money-check-dollar',
            check: 'fa-solid fa-money-check-dollar',
            manual: 'fa-solid fa-file-pen',
            other: 'fa-solid fa-ellipsis',
        };

        const resolvePaymentMethodIcon = (methodName) => {
            const key = normalizePaymentMethodKey(methodName);
            if (paymentMethodIconMap[key]) return paymentMethodIconMap[key];
            if (key.includes('credit')) return paymentMethodIconMap.creditcard;
            if (key.includes('debit')) return paymentMethodIconMap.debit;
            if (key.includes('transfer') || key.includes('etransfer')) return paymentMethodIconMap.etransfer;
            if (key.includes('check') || key.includes('cheque')) return paymentMethodIconMap.cheque;
            if (key.includes('ach') || key.includes('bank')) return paymentMethodIconMap.ach;
            return paymentMethodIconMap.other;
        };

        const resolvePaymentMethodLogos = (methodName) => {
            const key = normalizePaymentMethodKey(methodName);
            if (paymentMethodLogoMap[key]) return paymentMethodLogoMap[key];
            if (key.includes('credit')) return paymentMethodLogoMap.creditcard;
            if (key.includes('debit')) return paymentMethodLogoMap.debit;
            if (key.includes('transfer') || key.includes('etransfer')) return paymentMethodLogoMap.etransfer;
            if (key.includes('ach') || key.includes('bank')) return paymentMethodLogoMap.ach;
            if (key.includes('other')) return paymentMethodLogoMap.other;
            return [];
        };

        const resolvePaymentMethodFaFallback = (methodName) => {
            const key = normalizePaymentMethodKey(methodName);
            if (paymentMethodFaFallbackMap[key]) return paymentMethodFaFallbackMap[key];
            if (key.includes('credit')) return paymentMethodFaFallbackMap.creditcard;
            if (key.includes('debit')) return paymentMethodFaFallbackMap.debit;
            if (key.includes('transfer') || key.includes('etransfer')) return paymentMethodFaFallbackMap.etransfer;
            if (key.includes('check') || key.includes('cheque')) return paymentMethodFaFallbackMap.cheque;
            if (key.includes('ach') || key.includes('bank')) return paymentMethodFaFallbackMap.ach;
            return paymentMethodFaFallbackMap.other;
        };

        const buildPosMethodLogoMarkup = (methodName) => {
            const logos = resolvePaymentMethodLogos(methodName);
            if (logos.length) {
                const fallbackFile = resolvePaymentMethodIcon(methodName);
                return logos.map((slug) => {
                    const src = `${paymentMethodLogoCdnBase}/${encodeURIComponent(slug)}`;
                    return `<span class="pos-method-logo-chip"><img class="pos-method-icon pos-method-icon--brand" src="${escapeHtml(src)}" data-fallback-file="${escapeHtml(fallbackFile)}" alt="" aria-hidden="true" loading="lazy"></span>`;
                }).join('');
            }
            const faClass = resolvePaymentMethodFaFallback(methodName);
            return `<span class="pos-method-logo-chip"><i class="${faClass} pos-method-fa-icon" aria-hidden="true"></i></span>`;
        };

        const hydratePosMethodLogoFallbacks = (btn, methodName) => {
            if (!btn) return;
            const faClass = resolvePaymentMethodFaFallback(methodName);
            btn.querySelectorAll('img.pos-method-icon').forEach((img) => {
                img.addEventListener('error', () => {
                    const fallbackFile = (img.dataset.fallbackFile || '').trim();
                    const usedLocalFallback = img.dataset.usedLocalFallback === '1';
                    if (fallbackFile && posPaymentIconBase && !usedLocalFallback) {
                        img.dataset.usedLocalFallback = '1';
                        img.src = `${posPaymentIconBase}${fallbackFile}`;
                        img.classList.add('pos-method-icon--fallback');
                        return;
                    }
                    const fallbackIcon = document.createElement('i');
                    fallbackIcon.className = `${faClass} pos-method-fa-icon`;
                    fallbackIcon.setAttribute('aria-hidden', 'true');
                    const chip = img.closest('.pos-method-logo-chip');
                    if (chip) {
                        chip.replaceChildren(fallbackIcon);
                    } else {
                        img.replaceWith(fallbackIcon);
                    }
                });
            });
        };

        const posProductImageUrl = (p) => {
            const candidates = [p?.image_url, p?.image, p?.imageUrl, p?.thumbnail, p?.photo_url];
            for (const value of candidates) {
                if (typeof value === 'string' && value.trim()) return value.trim();
            }
            return '';
        };

        const posStockMeta = (p) => {
            const qty = Number(p?.quantity_in_stock);
            if (!Number.isFinite(qty)) return { label: 'Stock n/a', className: '' };
            if (qty <= 0) return { label: 'Out of stock', className: 'is-out' };
            if (qty < 5) return { label: `${qty} left`, className: '' };
            return { label: `${qty} in stock`, className: '' };
        };

        const posServiceItems = (() => {
            const items = [];
            (quickServiceCatalog || []).forEach(group => {
                const groupName = group?.name || 'Service';
                (group?.descriptions || []).forEach(desc => {
                    items.push({
                        id: desc.id,
                        group: groupName,
                        text: desc.text || '',
                        fixed_hours: desc.fixed_hours || '',
                        fixed_rate: desc.fixed_rate || '',
                    });
                });
            });
            return items;
        })();

        const renderPosProducts = () => {
            if (!posProductGrid) return;
            const q = (posSearchInput?.value || '').trim().toLowerCase();
            const list = (allProducts || []).filter(p => {
                const hay = `${p.name || ''} ${p.sku || ''} ${p.supplier || ''} ${p.description || ''}`.toLowerCase();
                return !q || hay.includes(q);
            }).slice(0, 60);
            if (!list.length) {
                posProductGrid.innerHTML = '<div class="pos-empty">No matching products.</div>';
                return;
            }
            posProductGrid.innerHTML = list.map(p => {
                const price = posPriceForProduct(p);
                const sku = p.sku ? `SKU ${escapeHtml(p.sku)}` : 'No SKU';
                const supplier = p.supplier ? escapeHtml(p.supplier) : 'Store stock';
                const title = escapeHtml(p.name || 'Product');
                const imageUrl = posProductImageUrl(p);
                const stock = posStockMeta(p);
                const cartItem = posCart.find(row => row.line_source === 'product' && String(row.product_id) === String(p.id));
                const inCart = !!cartItem;
                const cardClass = inCart ? 'pos-product-card is-in-cart' : 'pos-product-card';
                const badgeClass = inCart ? 'pos-add-badge is-added' : 'pos-add-badge';
                const badgeIcon = inCart ? 'fa-solid fa-check' : 'fa-solid fa-plus';
                const badgeLabel = inCart ? `Added (${posFormatQty(cartItem.qty)})` : 'Tap to add';
                const media = imageUrl
                    ? `<img src="${escapeHtml(imageUrl)}" alt="${title}" loading="lazy">`
                    : '<div class="pos-card-media-fallback"><i class="fa-solid fa-box-open"></i></div>';
                return `
                    <button type="button" class="${cardClass}" data-product-id="${p.id}" aria-pressed="${inCart ? 'true' : 'false'}">
                        <div class="pos-card-media">
                            ${media}
                            <span class="pos-stock-pill ${stock.className}">${escapeHtml(stock.label)}</span>
                        </div>
                        <div class="pos-card-body">
                            <div class="pos-product-title">${title}</div>
                            <div class="pos-product-meta">${sku}</div>
                            <div class="pos-product-meta">${supplier}</div>
                            <div class="pos-product-foot">
                                <div class="pos-product-price">${currencyFmt(price)}</div>
                                <div class="${badgeClass}"><i class="${badgeIcon}"></i>${badgeLabel}</div>
                            </div>
                        </div>
                    </button>
                `;
            }).join('');
        };

        const renderPosServices = () => {
            if (!posServiceGrid) return;
            const q = (posSearchInput?.value || '').trim().toLowerCase();
            const list = (posServiceItems || []).filter(s => {
                const hay = `${s.group || ''} ${s.text || ''}`.toLowerCase();
                return !q || hay.includes(q);
            }).slice(0, 60);
            if (!list.length) {
                posServiceGrid.innerHTML = '<div class="pos-empty">No matching services.</div>';
                return;
            }
            posServiceGrid.innerHTML = list.map(s => {
                const label = `${s.group}: ${s.text}`.trim();
                const rateLabel = s.fixed_rate !== '' ? currencyFmt(s.fixed_rate) : 'Set rate';
                return `
                    <button type="button" class="pos-service-card" data-service-id="${s.id}">
                        <div class="pos-card-media">
                            <div class="pos-card-media-fallback"><i class="fa-solid fa-screwdriver-wrench"></i></div>
                        </div>
                        <div class="pos-card-body">
                            <div class="pos-product-title">${escapeHtml(label)}</div>
                            <div class="pos-product-meta">Service</div>
                            <div class="pos-product-foot">
                                <div class="pos-product-price">${rateLabel}</div>
                                <div class="pos-add-badge"><i class="fa-solid fa-plus"></i>Tap to add</div>
                            </div>
                        </div>
                    </button>
                `;
            }).join('');
        };

        const addPosItem = (item) => {
            const existing = posCart.find(row => row.key === item.key);
            if (existing) {
                existing.qty = Number(existing.qty || 0) + Number(item.qty || 1);
            } else {
                posCart.push(item);
            }
            renderPosCart();
        };

        const focusPosCartLine = (key) => {
            if (!posCartLines || !key) return;
            const rows = Array.from(posCartLines.querySelectorAll('.pos-cart-line'));
            const row = rows.find((el) => String(el.dataset.key || '') === String(key));
            if (!row) return;
            row.classList.remove('pos-cart-line--focus');
            // restart animation for repeat clicks
            void row.offsetWidth;
            row.classList.add('pos-cart-line--focus');
            try {
                row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } catch (e) {
                // ignore browser scroll support differences
            }
        };

        const renderPosCart = () => {
            if (!posCartLines) return;
            if (!posCart.length) {
                posCartLines.innerHTML = '<div class="pos-empty">No items yet. Start by tapping a product.</div>';
                updatePosTotals();
                if (posActiveTab === 'products') renderPosProducts();
                return;
            }
            posCartLines.innerHTML = posCart.map(item => `
                <div class="pos-cart-line" data-key="${item.key}">
                    <div>
                        <div class="pos-line-title">${escapeHtml(item.label || item.job || 'Item')}</div>
                        <div class="pos-line-sub">${escapeHtml(item.meta || '')}</div>
                    </div>
                    <div class="pos-line-controls">
                        <div class="pos-qty">
                            <button type="button" class="pos-qty-btn" data-action="dec">-</button>
                            <input type="number" class="pos-qty-input" min="0" step="0.01" value="${item.qty}">
                            <button type="button" class="pos-qty-btn" data-action="inc">+</button>
                        </div>
                        <input type="number" class="pos-rate-input" min="0" step="0.01" value="${item.rate}">
                        <div class="pos-line-total">${formatLineTotal(item.qty, item.rate)}</div>
                        <button type="button" class="pos-remove" data-action="remove">x</button>
                    </div>
                </div>
            `).join('');
            updatePosTotals();
            if (posActiveTab === 'products') renderPosProducts();
        };

        const updatePosTotals = () => {
            const subtotal = posCart.reduce((sum, item) => sum + (Number(item.qty) || 0) * (Number(item.rate) || 0), 0);
            const tax = (posTaxExempt?.checked) ? 0 : subtotal * posTaxRate;
            const total = subtotal + tax;
            if (posSubtotalEl) posSubtotalEl.textContent = currencyFmt(subtotal);
            if (posTaxEl) posTaxEl.textContent = currencyFmt(tax);
            if (posTotalEl) posTotalEl.textContent = currencyFmt(total);
            updatePosPaymentAmount(total);
            updatePosChangeDue(total);
        };

        const updatePosPaymentAmount = (total) => {
            if (!posPaymentAmount || !posRecordPayment?.checked) return;
            if (!posPaymentAuto && posPaymentAmount.value !== '') return;
            posPaymentAmount.value = total.toFixed(2);
        };

        const updatePosChangeDue = (total) => {
            if (!posChangeDue) return;
            if (!posRecordPayment?.checked) {
                posChangeDue.textContent = '--';
                return;
            }
            const paid = Number(posPaymentAmount?.value || 0);
            const change = Math.max(0, paid - total);
            posChangeDue.textContent = currencyFmt(change);
        };

        const setPosMethod = (method) => {
            posActiveMethod = method;
            posMethodButtons.forEach(btn => {
                btn.classList.toggle('active', btn.dataset.method === method);
            });
        };

        const setPosPaymentEnabled = (enabled) => {
            posMethodButtons.forEach(btn => { btn.disabled = !enabled; });
            if (posPaymentAmount) posPaymentAmount.disabled = !enabled;
            if (posPayFull) posPayFull.disabled = !enabled;
        };

        const syncPosCheckoutButtons = () => {
            const paidFlow = !!posRecordPayment?.checked;
            posCheckoutActionButtons.forEach((btn) => {
                btn.classList.toggle('is-paid-flow', paidFlow);
            });
            posCheckoutLabels.forEach((label) => {
                const next = paidFlow
                    ? (label.dataset.paidLabel || label.textContent || '')
                    : (label.dataset.defaultLabel || label.textContent || '');
                label.innerHTML = next;
            });
        };

        const iconizePosMethodButtons = () => {
            if (!posMethodsContainer || !posMethodButtons.length) return;
            posMethodsContainer.classList.add('is-iconized', 'is-logoized');
            posMethodButtons.forEach((btn) => {
                const methodName = (btn.dataset.method || btn.textContent || '').trim();
                const logosMarkup = buildPosMethodLogoMarkup(methodName);
                btn.innerHTML = `<span class="pos-method-logo-group">${logosMarkup}</span><span class="pos-method-label">${escapeHtml(methodName)}</span>`;
                btn.setAttribute('title', methodName);
                btn.setAttribute('aria-label', methodName);
                hydratePosMethodLogoFallbacks(btn, methodName);
                const logoCount = btn.querySelectorAll('.pos-method-logo-chip').length;
                btn.classList.toggle('has-multi-logo', logoCount > 1);
            });
        };

        iconizePosMethodButtons();

        posMethodButtons.forEach(btn => {
            btn.addEventListener('click', () => setPosMethod(btn.dataset.method));
        });
        if (posActiveMethod) setPosMethod(posActiveMethod);

        posTabButtons.forEach(btn => {
            btn.addEventListener('click', () => setPosTab(btn.dataset.posTab || 'products'));
        });

        posSearchInput?.addEventListener('input', () => {
            if (posActiveTab === 'products') renderPosProducts();
            if (posActiveTab === 'services') renderPosServices();
        });
        posSearchClear?.addEventListener('click', () => {
            if (posSearchInput) posSearchInput.value = '';
            if (posActiveTab === 'products') renderPosProducts();
            if (posActiveTab === 'services') renderPosServices();
        });

        posProductGrid?.addEventListener('click', (e) => {
            const card = e.target.closest('[data-product-id]');
            if (!card) return;
            const productId = card.dataset.productId;
            const p = (allProducts || []).find(row => String(row.id) === String(productId));
            if (!p) return;
            const existing = posCart.find(row => row.line_source === 'product' && String(row.product_id) === String(p.id));
            if (existing) {
                focusPosCartLine(existing.key);
                showStatus('info', `${p.name || 'Product'} is already in cart. Update quantity in Current sale.`);
                return;
            }
            const price = posPriceForProduct(p);
            addPosItem({
                key: `product-${p.id}`,
                label: p.name || 'Product',
                meta: p.sku ? `SKU ${p.sku}` : 'Part',
                qty: 1,
                rate: price.toFixed(2),
                line_source: 'product',
                product_id: p.id,
                service_id: '',
                job: `part - ${p.name || 'Product'}`,
            });
        });

        posServiceGrid?.addEventListener('click', (e) => {
            const card = e.target.closest('[data-service-id]');
            if (!card) return;
            const serviceId = card.dataset.serviceId;
            const s = (posServiceItems || []).find(row => String(row.id) === String(serviceId));
            if (!s) return;
            const qty = s.fixed_hours !== '' ? Number(s.fixed_hours) : 1;
            const rate = s.fixed_rate !== '' ? Number(s.fixed_rate) : 0;
            addPosItem({
                key: `service-${s.id}`,
                label: `${s.group}: ${s.text}`.trim(),
                meta: 'Service',
                qty: Number.isFinite(qty) ? qty : 1,
                rate: Number.isFinite(rate) ? rate.toFixed(2) : '0.00',
                line_source: 'service',
                product_id: '',
                service_id: s.id,
                job: `service - ${s.text || s.group || 'Service'}`,
            });
        });

        posCustomAdd?.addEventListener('click', () => {
            const name = (posCustomName?.value || '').trim();
            const qty = Number(posCustomQty?.value || 1);
            const rate = Number(posCustomRate?.value || 0);
            if (!name) {
                showStatus('danger', 'Enter a custom description.');
                return;
            }
            const key = `custom-${Date.now()}`;
            addPosItem({
                key,
                label: name,
                meta: 'Custom',
                qty: Number.isFinite(qty) ? qty : 1,
                rate: Number.isFinite(rate) ? rate.toFixed(2) : '0.00',
                line_source: 'custom',
                product_id: '',
                service_id: '',
                job: name,
            });
            if (posCustomName) posCustomName.value = '';
            if (posCustomRate) posCustomRate.value = '';
            if (posCustomQty) posCustomQty.value = '1';
        });

        posCustomEntry?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                posCustomAdd?.click();
            }
        });

        posCartLines?.addEventListener('click', (e) => {
            const row = e.target.closest('.pos-cart-line');
            if (!row) return;
            const key = row.dataset.key;
            const item = posCart.find(r => r.key === key);
            if (!item) return;
            const actionBtn = e.target.closest('[data-action]');
            if (!actionBtn) return;
            const action = actionBtn.dataset.action;
            if (action === 'remove') {
                posCart = posCart.filter(r => r.key !== key);
                renderPosCart();
                return;
            }
            if (action === 'inc') item.qty = Number(item.qty || 0) + 1;
            if (action === 'dec') item.qty = Math.max(0, Number(item.qty || 0) - 1);
            if (item.qty <= 0) posCart = posCart.filter(r => r.key !== key);
            renderPosCart();
        });

        posCartLines?.addEventListener('input', (e) => {
            const row = e.target.closest('.pos-cart-line');
            if (!row) return;
            const key = row.dataset.key;
            const item = posCart.find(r => r.key === key);
            if (!item) return;
            if (e.target.classList.contains('pos-qty-input')) {
                const val = Number(e.target.value || 0);
                item.qty = Number.isFinite(val) ? val : 0;
            }
            if (e.target.classList.contains('pos-rate-input')) {
                const val = Number(e.target.value || 0);
                item.rate = Number.isFinite(val) ? val.toFixed(2) : '0.00';
            }
            const totalEl = row.querySelector('.pos-line-total');
            if (totalEl) totalEl.textContent = formatLineTotal(item.qty, item.rate);
            updatePosTotals();
            if (posActiveTab === 'products') renderPosProducts();
        });

        posTaxExempt?.addEventListener('change', updatePosTotals);
        posPaymentAmount?.addEventListener('input', () => {
            posPaymentAuto = false;
            updatePosChangeDue(Number(posTotalEl?.textContent?.replace(/[^0-9.-]+/g, '') || 0));
        });
        posPayFull?.addEventListener('click', () => {
            posPaymentAuto = true;
            updatePosTotals();
        });
        posRecordPayment?.addEventListener('change', () => {
            setPosPaymentEnabled(!!posRecordPayment?.checked);
            syncPosCheckoutButtons();
            updatePosTotals();
        });

        posClearCart?.addEventListener('click', () => {
            posCart = [];
            renderPosCart();
        });

        const buildPosInvoiceUrl = (template, invoiceId) => {
            if (!template) return '';
            return template.replace('/0/', `/${invoiceId}/`);
        };

        const recordPosPayment = async (invoiceId, amount) => {
            if (!posPaymentUrlTemplate) return;
            const url = buildPosInvoiceUrl(posPaymentUrlTemplate, invoiceId);
            const payload = new FormData();
            payload.append('csrfmiddlewaretoken', getCsrfToken());
            payload.append('grouped_invoice_id', String(invoiceId));
            payload.append('amount', String(amount.toFixed(2)));
            payload.append('method', posActiveMethod || 'Manual');
            payload.append('payment_date', posSaleDate?.value || '');
            payload.append('notes', 'POS checkout');
            const resp = await fetch(url, {
                method: 'POST',
                body: payload,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.status === 'error') {
                const msg = data.message || 'Unable to record payment.';
                throw new Error(msg);
            }
            const parsedBalance = Number(String(data.balance_due || '').replace(/[^0-9.-]+/g, ''));
            return {
                balanceDue: Number.isFinite(parsedBalance) ? parsedBalance : null,
            };
        };

        const sendPosInvoiceEmail = async (invoiceId, { usePaidReceipt = false } = {}) => {
            const template = usePaidReceipt
                ? (posSendPaidEmailUrlTemplate || posSendEmailUrlTemplate)
                : posSendEmailUrlTemplate;
            if (!template) {
                throw new Error('Invoice email endpoint is not configured.');
            }
            const url = buildPosInvoiceUrl(template, invoiceId);
            const payload = new FormData();
            payload.append('csrfmiddlewaretoken', getCsrfToken());
            payload.append('async', '1');
            const resp = await fetch(url, {
                method: 'POST',
                body: payload,
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.error) {
                const msg = data.error || data.message || (usePaidReceipt ? 'Unable to send receipt email.' : 'Unable to send invoice email.');
                throw new Error(msg);
            }
        };

        const openPosInvoicePrint = (invoiceId, { usePaidReceipt = false } = {}) => {
            const template = usePaidReceipt
                ? (posPaidPrintUrlTemplate || posPrintUrlTemplate)
                : posPrintUrlTemplate;
            if (!template) {
                throw new Error('Invoice print endpoint is not configured.');
            }
            const printUrl = buildPosInvoiceUrl(template, invoiceId);
            window.open(printUrl, '_blank', 'noopener');
        };

        const submitPos = async ({ recordPayment = true, checkoutAction = 'none' } = {}) => {
            if (!posCustomerIdInput?.value) {
                showStatus('danger', 'Select a customer before checkout.');
                return;
            }
            if (!posCart.length) {
                showStatus('danger', 'Add at least one item to the cart.');
                return;
            }
            const emailAction = checkoutAction === 'email' || checkoutAction === 'email_print';
            if (emailAction) {
                const selectedCustomer = (quickCustomers || []).find((c) => String(c.id) === String(posCustomerIdInput?.value || ''));
                const enteredEmail = (posEmail?.value || '').trim();
                const customerEmail = (selectedCustomer?.email || '').trim();
                if (selectedCustomer && !enteredEmail && !customerEmail) {
                    showStatus('danger', 'Enter an email to send the receipt/invoice.');
                    return;
                }
            }
            const fd = new FormData();
            fd.append('csrfmiddlewaretoken', getCsrfToken());
            fd.append('customer', posCustomerIdInput.value);
            if (posVehicleIdInput?.value) fd.append('vehicle', posVehicleIdInput.value);
            if (posSaleDate?.value) fd.append('date', posSaleDate.value);
            if (posEmail?.value) fd.append('bill_to_email', posEmail.value);
            if (posTaxExempt?.checked) fd.append('tax_exempt', 'on');
            fd.append('post_action', 'continue');

            posCart.forEach(item => {
                fd.append('line_source', item.line_source || 'custom');
                fd.append('product_id', item.product_id || '');
                fd.append('service_id', item.service_id || '');
                fd.append('job', item.job || item.label || 'Item');
                fd.append('qty', String(item.qty || 0));
                fd.append('rate', String(item.rate || 0));
            });

            let savedInvoiceId = null;
            try {
                const resp = await fetch(posForm.action, {
                    method: 'POST',
                    body: fd,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    const msg = (data && data.errors) ? extractFirstError(data.errors) : null;
                    throw new Error(msg || 'Unable to create invoice.');
                }
                const invoiceId = data.invoice_id;
                savedInvoiceId = invoiceId;
                const subtotal = posCart.reduce((sum, item) => sum + (Number(item.qty) || 0) * (Number(item.rate) || 0), 0);
                const tax = (posTaxExempt?.checked) ? 0 : subtotal * posTaxRate;
                const grandTotal = subtotal + tax;
                let paymentCaptured = false;
                let paidInFull = false;

                if (recordPayment && posRecordPayment?.checked && grandTotal > 0) {
                    let paid = Number(posPaymentAmount?.value || 0);
                    if (!Number.isFinite(paid) || paid <= 0) paid = grandTotal;
                    if (paid > grandTotal) paid = grandTotal;
                    const paymentResult = await recordPosPayment(invoiceId, paid);
                    paymentCaptured = paid > 0;
                    if (paymentResult && paymentResult.balanceDue != null) {
                        paidInFull = paymentResult.balanceDue <= 0.009;
                    } else {
                        paidInFull = (paid + 0.01) >= grandTotal;
                    }
                }
                const usePaidReceipt = paymentCaptured && paidInFull;

                if (checkoutAction === 'email') {
                    await sendPosInvoiceEmail(invoiceId, { usePaidReceipt });
                } else if (checkoutAction === 'print') {
                    openPosInvoicePrint(invoiceId, { usePaidReceipt });
                } else if (checkoutAction === 'email_print') {
                    await sendPosInvoiceEmail(invoiceId, { usePaidReceipt });
                    openPosInvoicePrint(invoiceId, { usePaidReceipt });
                }

                const successMessage = checkoutAction === 'email'
                    ? (usePaidReceipt ? 'Payment recorded. Receipt email queued.' : 'POS sale saved and invoice email queued.')
                    : checkoutAction === 'print'
                        ? (usePaidReceipt ? 'Payment recorded. Receipt print view opened.' : 'POS sale saved and invoice print view opened.')
                        : checkoutAction === 'email_print'
                            ? (usePaidReceipt ? 'Payment recorded. Receipt email queued and print view opened.' : 'POS sale saved. Invoice email queued and print view opened.')
                            : 'POS sale saved.';
                showStatus('success', successMessage);
                posCart = [];
                renderPosCart();
                if (posPaymentAmount) posPaymentAmount.value = '';
                posPaymentAuto = true;
            } catch (err) {
                if (savedInvoiceId) {
                    showStatus('warning', `Invoice #${savedInvoiceId} was saved, but ${err.message || 'a follow-up step failed.'}`);
                } else {
                    showStatus('danger', err.message || 'Unable to complete POS checkout.');
                }
            }
        };

        posSaveSale?.addEventListener('click', () => submitPos({ recordPayment: false }));
        posCheckoutEmailBtn?.addEventListener('click', () => submitPos({ recordPayment: true, checkoutAction: 'email' }));
        posCheckoutPrintBtn?.addEventListener('click', () => submitPos({ recordPayment: true, checkoutAction: 'print' }));
        posCheckoutEmailPrintBtn?.addEventListener('click', () => submitPos({ recordPayment: true, checkoutAction: 'email_print' }));

        // Quick add customer / vehicle
        const addCustomerModalEl = document.getElementById('quickInvoiceAddCustomerModal');
        const addCustomerModal = addCustomerModalEl && window.bootstrap ? new bootstrap.Modal(addCustomerModalEl) : null;
        const addCustomerName = document.getElementById('quick-add-customer-name');
        const addCustomerEmail = document.getElementById('quick-add-customer-email');
        const addCustomerCc = document.getElementById('quick-add-customer-cc');
        const addCustomerAddress = document.getElementById('quick-add-customer-address');
        const addCustomerSave = document.getElementById('quick-add-customer-save');
        const addCustomerError = document.getElementById('quick-add-customer-error');

        const addVehicleModalEl = document.getElementById('quickInvoiceAddVehicleModal');
        const addVehicleModal = addVehicleModalEl && window.bootstrap ? new bootstrap.Modal(addVehicleModalEl) : null;
        const addVehicleUnit = document.getElementById('quick-add-vehicle-unit');
        const addVehicleMakeModel = document.getElementById('quick-add-vehicle-make-model');
        const addVehicleYear = document.getElementById('quick-add-vehicle-year');
        const addVehiclePlate = document.getElementById('quick-add-vehicle-plate');
        const addVehicleVin = document.getElementById('quick-add-vehicle-vin');
        const addVehicleMileage = document.getElementById('quick-add-vehicle-mileage');
        const addVehicleSave = document.getElementById('quick-add-vehicle-save');
        const addVehicleError = document.getElementById('quick-add-vehicle-error');

        const showInlineError = (el, message) => {
            if (!el) return;
            el.textContent = message || 'Unable to save.';
            el.classList.remove('d-none');
        };
        const clearInlineError = (el) => {
            if (!el) return;
            el.textContent = '';
            el.classList.add('d-none');
        };

        posAddCustomerBtn?.addEventListener('click', () => {
            clearInlineError(addCustomerError);
            if (addCustomerName) addCustomerName.value = '';
            if (addCustomerEmail) addCustomerEmail.value = '';
            if (addCustomerCc) addCustomerCc.value = '';
            if (addCustomerAddress) addCustomerAddress.value = '';
            addCustomerModal?.show();
            setTimeout(() => addCustomerName?.focus(), 150);
        });

        addCustomerSave?.addEventListener('click', async () => {
            clearInlineError(addCustomerError);
            if (!posAddCustomerUrl) return;
            addCustomerSave.disabled = true;
            try {
                const payload = new FormData();
                payload.append('name', (addCustomerName?.value || '').trim());
                payload.append('email', (addCustomerEmail?.value || '').trim());
                payload.append('cc_emails', (addCustomerCc?.value || '').trim());
                payload.append('address', (addCustomerAddress?.value || '').trim());
                payload.append('collect_gst_hst_choice', 'False');
                payload.append('csrfmiddlewaretoken', getCsrfToken());

                const resp = await fetch(posAddCustomerUrl, {
                    method: 'POST',
                    body: payload,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    const msg = (data && data.errors) ? extractFirstError(data.errors) : null;
                    throw new Error(msg || 'Unable to save customer.');
                }
                const c = data.customer || {};
                try { quickCustomers.push({ id: c.id, name: c.name, email: c.email }); } catch (e) { /* ignore */ }
                renderPosCustomerList();
                selectPosCustomer(String(c.id));
                addCustomerModal?.hide();
                showStatus('success', 'Customer added.');
            } catch (err) {
                showInlineError(addCustomerError, err.message || 'Unable to save customer.');
            } finally {
                addCustomerSave.disabled = false;
            }
        });

        posAddVehicleBtn?.addEventListener('click', () => {
            clearInlineError(addVehicleError);
            if (!posCustomerIdInput?.value) return;
            if (addVehicleUnit) addVehicleUnit.value = '';
            if (addVehicleMakeModel) addVehicleMakeModel.value = '';
            if (addVehicleYear) addVehicleYear.value = '';
            if (addVehiclePlate) addVehiclePlate.value = '';
            if (addVehicleVin) addVehicleVin.value = '';
            if (addVehicleMileage) addVehicleMileage.value = '';
            addVehicleModal?.show();
            setTimeout(() => addVehicleUnit?.focus(), 150);
        });

        addVehicleSave?.addEventListener('click', async () => {
            clearInlineError(addVehicleError);
            const customerId = posCustomerIdInput?.value;
            if (!customerId || !posAddVehicleUrl) return;
            addVehicleSave.disabled = true;
            try {
                const payload = new FormData();
                payload.append('customer', customerId);
                payload.append('unit_number', (addVehicleUnit?.value || '').trim());
                payload.append('make_model', (addVehicleMakeModel?.value || '').trim());
                payload.append('year', (addVehicleYear?.value || '').trim());
                payload.append('license_plate', (addVehiclePlate?.value || '').trim());
                payload.append('vin_number', (addVehicleVin?.value || '').trim());
                payload.append('current_mileage', (addVehicleMileage?.value || '').trim());
                payload.append('csrfmiddlewaretoken', getCsrfToken());

                const resp = await fetch(posAddVehicleUrl, {
                    method: 'POST',
                    body: payload,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || !data.success) {
                    const msg = (data && data.errors) ? extractFirstError(data.errors) : null;
                    throw new Error(msg || 'Unable to save vehicle.');
                }
                const v = data.vehicle || {};
                const newVehicle = {
                    id: v.id,
                    customer_id: Number(customerId),
                    unit_number: v.unit_no || '',
                    make_model: v.make_model || '',
                    year: v.year || '',
                    license_plate: v.license_plate || '',
                    vin: v.vin_no || '',
                    current_mileage: v.current_mileage || '',
                };
                try { quickVehicles.push(newVehicle); } catch (e) { /* ignore */ }
                renderPosVehicleList();
                selectPosVehicle(String(v.id));
                addVehicleModal?.hide();
                showStatus('success', 'Vehicle added.');
            } catch (err) {
                showInlineError(addVehicleError, err.message || 'Unable to save vehicle.');
            } finally {
                addVehicleSave.disabled = false;
            }
        });

        setPosTab('products');
        renderPosProducts();
        renderPosServices();
        renderPosCart();
        setPosPaymentEnabled(!!posRecordPayment?.checked);
        syncPosCheckoutButtons();
    }

    const overduePanel = document.getElementById('overdue-customers-panel');
    if (overduePanel) {
        let overdueCustomersRaw = [];
        try {
            const raw = JSON.parse(document.getElementById('parts-overdue-customers-data')?.textContent || '[]');
            overdueCustomersRaw = normalizeToArray(raw);
        } catch (e) {
            overdueCustomersRaw = [];
        }

        const overdueTbody = document.getElementById('overdue-tbody');
        const overdueSearch = document.getElementById('overdue-search');
        const overdueFirst = document.getElementById('overdue-first');
        const overduePrev = document.getElementById('overdue-prev');
        const overdueNext = document.getElementById('overdue-next');
        const overdueLast = document.getElementById('overdue-last');
        const overduePageInfo = document.getElementById('overdue-page-info');
        const overdueExpandBtn = document.getElementById('overdue-expand-btn');

        const overdueCustomers = (overdueCustomersRaw || []).slice().sort((a, b) => (b.balance_due || 0) - (a.balance_due || 0));
        let overduePage = 1;
        const overduePageSize = 10;
        let overdueQuery = '';

        const reminderUrlFor = (customerId) => (overduePanel?.dataset.reminderUrlTemplate || '').replace('/0/', `/${customerId}/`);
        const recordPaymentUrlFor = (customerId) => (overduePanel?.dataset.recordPaymentUrlTemplate || '').replace('/0/', `/${customerId}/`);
        const followupUrlFor = (customerId) => (overduePanel?.dataset.followupUrlTemplate || '').replace('/0/', `/${customerId}/`);
        const invoiceDetailUrlFor = (invoiceId) => (overduePanel?.dataset.invoiceDetailUrlTemplate || '').replace('/0/', `/${invoiceId}/`);

        const filteredOverdue = () => {
            const q = (overdueQuery || '').trim().toLowerCase();
            if (!q) return overdueCustomers;
            return overdueCustomers.filter((r) => {
                const haystack = `${r.customer_name || ''} ${r.customer_phone || ''}`.toLowerCase();
                return haystack.includes(q);
            });
        };

        const buildRow = (row, includeFollowup) => {
            const sent = !!row.sent_today;
            const btnClass = sent ? 'btn-success' : 'btn-primary';
            const btnLabel = sent ? 'Sent' : 'Send';
            const disabledAttr = sent ? 'disabled' : '';
            const customerName = row.customer_name || '';
            const customerNameSafe = escapeHtml(customerName);
            const customerPhoneSafe = escapeHtml(row.customer_phone || '');
            const followupCell = includeFollowup ? `
                <td>
                    <input type="date" class="form-control form-control-sm overdue-next-followup"
                        data-customer-id="${row.customer_id}"
                        value="${escapeHtml(row.next_followup || '')}">
                </td>
                <td>
                    <textarea class="form-control form-control-sm overdue-collection-notes"
                        data-customer-id="${row.customer_id}"
                        rows="2" placeholder="Add note...">${escapeHtml(row.collection_notes || '')}</textarea>
                </td>` : '';
            return `
                <tr>
                    <td>${customerNameSafe}</td>
                    <td>${customerPhoneSafe}</td>
                    <td>${formatLastSent(row.last_sent)}</td>
                    <td class="text-end">${currencyFmt(row.balance_due)}</td>
                    ${followupCell}
                    <td class="text-end">
                        <button class="btn btn-outline-primary btn-sm overdue-payment-btn"
                            data-customer-id="${row.customer_id}"
                            data-customer-name="${customerName.replace(/"/g, '&quot;')}"
                            data-outstanding="${row.outstanding_due || row.balance_due || 0}">
                            Record
                        </button>
                    </td>
                    <td class="text-end">
                        <button class="btn ${btnClass} btn-sm overdue-reminder-btn" data-customer-id="${row.customer_id}" ${disabledAttr}>${btnLabel}</button>
                    </td>
                </tr>`;
        };

        const renderOverdueTable = () => {
            if (!overdueTbody) return;
            const items = filteredOverdue();
            const totalPages = Math.max(1, Math.ceil(items.length / overduePageSize));
            overduePage = Math.max(1, Math.min(overduePage, totalPages));
            const start = (overduePage - 1) * overduePageSize;
            const pageItems = items.slice(start, start + overduePageSize);
            if (!pageItems.length) {
                overdueTbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center py-3">No overdue customers.</td></tr>';
            } else {
                overdueTbody.innerHTML = pageItems.map(row => buildRow(row, false)).join('');
            }
            const displayStart = items.length ? start + 1 : 0;
            const displayEnd = Math.min(start + overduePageSize, items.length);
            if (overduePageInfo) overduePageInfo.textContent = `${displayStart}-${displayEnd} of ${items.length}`;
            overdueFirst && (overdueFirst.disabled = overduePage <= 1);
            overduePrev && (overduePrev.disabled = overduePage <= 1);
            overdueNext && (overdueNext.disabled = overduePage >= totalPages);
            overdueLast && (overdueLast.disabled = overduePage >= totalPages);
        };

        const overdueFollowupTimers = new Map();
        const overdueFollowupPending = new Map();
        const queueOverdueFollowupSave = (customerId, updates) => {
            if (!customerId || !updates) return;
            const pending = overdueFollowupPending.get(customerId) || {};
            Object.assign(pending, updates);
            overdueFollowupPending.set(customerId, pending);
            if (overdueFollowupTimers.has(customerId)) {
                clearTimeout(overdueFollowupTimers.get(customerId));
            }
            overdueFollowupTimers.set(
                customerId,
                setTimeout(() => {
                    const payload = overdueFollowupPending.get(customerId) || {};
                    overdueFollowupPending.delete(customerId);
                    overdueFollowupTimers.delete(customerId);
                    saveOverdueFollowup(customerId, payload);
                }, 600)
            );
        };

        const saveOverdueFollowup = async (customerId, updates) => {
            const url = followupUrlFor(customerId);
            if (!url || !updates) return;
            const formData = new FormData();
            if (Object.prototype.hasOwnProperty.call(updates, 'next_followup')) {
                formData.append('next_followup', updates.next_followup || '');
            }
            if (Object.prototype.hasOwnProperty.call(updates, 'collection_notes')) {
                formData.append('notes', updates.collection_notes || '');
            }
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                    body: formData,
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.status !== 'success') throw new Error(data.message || 'Unable to save follow-up.');
                const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                if (idx >= 0) {
                    if (Object.prototype.hasOwnProperty.call(updates, 'next_followup')) {
                        overdueCustomers[idx].next_followup = data.next_followup || '';
                    }
                    if (Object.prototype.hasOwnProperty.call(updates, 'collection_notes')) {
                        overdueCustomers[idx].collection_notes = data.collection_notes || '';
                    }
                }
            } catch (err) {
                showStatus('danger', err.message || 'Unable to save follow-up.');
            }
        };

        const customerPaymentModalEl = document.getElementById('customerPaymentModal');
        const customerPaymentSuccessModalEl = document.getElementById('customerPaymentSuccessModal');
        const customerPaymentModal = customerPaymentModalEl && window.bootstrap ? new bootstrap.Modal(customerPaymentModalEl) : null;
        const customerPaymentSuccessModal = customerPaymentSuccessModalEl && window.bootstrap ? new bootstrap.Modal(customerPaymentSuccessModalEl) : null;

        const customerPaymentForm = document.getElementById('customer-payment-form');
        const customerPaymentCustomerId = document.getElementById('customer-payment-customer-id');
        const customerPaymentCustomerName = document.getElementById('customer-payment-customer-name');
        const customerPaymentOutstanding = document.getElementById('customer-payment-outstanding');
        const customerPaymentAmount = document.getElementById('customer-payment-amount');
        const customerPaymentDate = document.getElementById('customer-payment-date');
        const customerPaymentMethod = document.getElementById('customer-payment-method');
        const customerPaymentNotes = document.getElementById('customer-payment-notes');
        const customerPaymentSubmit = document.getElementById('customer-payment-submit');
        const customerPaymentSuccessMsg = document.getElementById('customer-payment-success-message');
        const customerPaymentSuccessRows = document.getElementById('customer-payment-success-rows');
        const customerPaymentStatementButtons = document.getElementById('customer-payment-statement-buttons');

        const openCustomerPaymentModal = ({ customerId, customerName, outstanding }) => {
            if (!customerPaymentModal || !customerPaymentModalEl) return;
            const today = customerPaymentModalEl.getAttribute('data-today') || '';
            const outNum = Number(outstanding || 0);
            if (customerPaymentCustomerId) customerPaymentCustomerId.value = customerId || '';
            if (customerPaymentCustomerName) customerPaymentCustomerName.textContent = customerName || 'Customer';
            if (customerPaymentOutstanding) customerPaymentOutstanding.textContent = currencyFmt(outNum);
            if (customerPaymentAmount) {
                customerPaymentAmount.value = outNum ? outNum.toFixed(2) : '';
                customerPaymentAmount.readOnly = false;
            }
            if (customerPaymentDate) customerPaymentDate.value = today;
            if (customerPaymentMethod) customerPaymentMethod.selectedIndex = 0;
            if (customerPaymentNotes) customerPaymentNotes.value = '';
            customerPaymentModal.show();
        };

        overdueSearch?.addEventListener('input', () => { overdueQuery = overdueSearch.value || ''; overduePage = 1; renderOverdueTable(); });
        overdueFirst?.addEventListener('click', () => { overduePage = 1; renderOverdueTable(); });
        overduePrev?.addEventListener('click', () => { overduePage = Math.max(1, overduePage - 1); renderOverdueTable(); });
        overdueNext?.addEventListener('click', () => { overduePage += 1; renderOverdueTable(); });
        overdueLast?.addEventListener('click', () => {
            const totalPages = Math.max(1, Math.ceil(filteredOverdue().length / overduePageSize));
            overduePage = totalPages;
            renderOverdueTable();
        });

        overdueTbody?.addEventListener('click', async (e) => {
            const payBtn = e.target.closest('.overdue-payment-btn');
            if (payBtn) {
                const customerId = payBtn.dataset.customerId;
                const customerName = payBtn.dataset.customerName || '';
                const outstanding = payBtn.dataset.outstanding;
                if (customerId) openCustomerPaymentModal({ customerId, customerName, outstanding });
                return;
            }
            const btn = e.target.closest('.overdue-reminder-btn');
            if (!btn) return;
            const customerId = btn.dataset.customerId;
            if (!customerId) return;
            btn.disabled = true;
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline-secondary');
            btn.textContent = 'Sending...';
            try {
                const resp = await fetch(reminderUrlFor(customerId), {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(data.error || 'Unable to send reminder.');
                const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                if (idx >= 0) overdueCustomers[idx].sent_today = true;
                showStatus('success', data.message || 'Reminder sent.');
            } catch (err) {
                const msg = err.message || 'Unable to send reminder.';
                if ((msg || '').toLowerCase().includes('already sent')) {
                    const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                    if (idx >= 0) overdueCustomers[idx].sent_today = true;
                }
                showStatus('danger', msg);
            } finally {
                renderOverdueTable();
            }
        });

        const openOverdueModal = () => {
            const items = filteredOverdue();
            const modalHtml = `
                <div class="modal fade" id="overdueCustomersModal" tabindex="-1">
                    <div class="modal-dialog modal-xl modal-dialog-scrollable modal-fullscreen-lg-down"><div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Overdue Customers</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="d-flex justify-content-between align-items-center gap-2 flex-wrap mb-2">
                                <div class="small text-muted">Showing <strong>${items.length}</strong> customers</div>
                                <input type="text" class="form-control form-control-sm" id="overdue-modal-search" placeholder="Search customer..." value="${(overdueQuery || '').replace(/"/g, '&quot;')}" style="min-width: 220px;">
                            </div>
                            <div class="table-responsive">
                                <table class="table table-sm">
                                    <thead><tr><th>Customer</th><th>Phone</th><th>Last statement</th><th class="text-end">Balance Due</th><th>Next followup</th><th>Notes</th><th class="text-end">Payment</th><th class="text-end">Reminder</th></tr></thead>
                                    <tbody id="overdue-modal-tbody"></tbody>
                                </table>
                            </div>
                            <div class="d-flex justify-content-between align-items-center mt-2">
                                <div class="small text-muted" id="overdue-modal-page-info"></div>
                                <div class="d-flex gap-2">
                                    <button class="btn btn-outline-secondary btn-sm" id="overdue-modal-first">First</button>
                                    <button class="btn btn-outline-secondary btn-sm" id="overdue-modal-prev">Previous</button>
                                    <button class="btn btn-outline-secondary btn-sm" id="overdue-modal-next">Next</button>
                                    <button class="btn btn-outline-secondary btn-sm" id="overdue-modal-last">Last</button>
                                </div>
                            </div>
                        </div>
                    </div></div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', modalHtml);
            const modalEl = document.getElementById('overdueCustomersModal');
            const modal = new bootstrap.Modal(modalEl);
            modalEl.addEventListener('hidden.bs.modal', () => modalEl.remove());

            let page = 1;
            const pageSize = 10;
            const modalSearch = modalEl.querySelector('#overdue-modal-search');
            const modalTbody = modalEl.querySelector('#overdue-modal-tbody');
            const modalFirst = modalEl.querySelector('#overdue-modal-first');
            const modalPrev = modalEl.querySelector('#overdue-modal-prev');
            const modalNext = modalEl.querySelector('#overdue-modal-next');
            const modalLast = modalEl.querySelector('#overdue-modal-last');
            const modalInfo = modalEl.querySelector('#overdue-modal-page-info');

            const modalFiltered = () => {
                const q = (modalSearch.value || '').trim().toLowerCase();
                overdueQuery = modalSearch.value || '';
                if (!q) return overdueCustomers;
                return overdueCustomers.filter((r) => {
                    const haystack = `${r.customer_name || ''} ${r.customer_phone || ''}`.toLowerCase();
                    return haystack.includes(q);
                });
            };

            const renderModal = () => {
                const list = modalFiltered().slice().sort((a, b) => (b.balance_due || 0) - (a.balance_due || 0));
                const totalPages = Math.max(1, Math.ceil(list.length / pageSize));
                page = Math.max(1, Math.min(page, totalPages));
                const start = (page - 1) * pageSize;
                const slice = list.slice(start, start + pageSize);
                modalTbody.innerHTML = slice.map(row => buildRow(row, true)).join('') || '<tr><td colspan="8" class="text-muted text-center py-3">No overdue customers.</td></tr>';
                const displayStart = list.length ? start + 1 : 0;
                const displayEnd = Math.min(start + pageSize, list.length);
                modalInfo.textContent = `${displayStart}-${displayEnd} of ${list.length}`;
                modalFirst.disabled = page <= 1;
                modalPrev.disabled = page <= 1;
                modalNext.disabled = page >= totalPages;
                modalLast.disabled = page >= totalPages;
            };

            modalSearch.addEventListener('input', () => { page = 1; renderModal(); });
            modalFirst.addEventListener('click', () => { page = 1; renderModal(); });
            modalPrev.addEventListener('click', () => { page = Math.max(1, page - 1); renderModal(); });
            modalNext.addEventListener('click', () => { page += 1; renderModal(); });
            modalLast.addEventListener('click', () => {
                page = Math.max(1, Math.ceil(modalFiltered().length / pageSize));
                renderModal();
            });

            modalTbody.addEventListener('click', async (e) => {
                const payBtn = e.target.closest('.overdue-payment-btn');
                if (payBtn) {
                    const customerId = payBtn.dataset.customerId;
                    const customerName = payBtn.dataset.customerName || '';
                    const outstanding = payBtn.dataset.outstanding;
                    if (customerId) {
                        modal.hide();
                        openCustomerPaymentModal({ customerId, customerName, outstanding });
                    }
                    return;
                }
                const btn = e.target.closest('.overdue-reminder-btn');
                if (!btn) return;
                const customerId = btn.dataset.customerId;
                if (!customerId) return;
                btn.disabled = true;
                btn.classList.remove('btn-primary');
                btn.classList.add('btn-outline-secondary');
                btn.textContent = 'Sending...';
                try {
                    const resp = await fetch(reminderUrlFor(customerId), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                    });
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok) throw new Error(data.error || 'Unable to send reminder.');
                    const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                    if (idx >= 0) overdueCustomers[idx].sent_today = true;
                    showStatus('success', data.message || 'Reminder sent.');
                } catch (err) {
                    const msg = err.message || 'Unable to send reminder.';
                    if ((msg || '').toLowerCase().includes('already sent')) {
                        const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                        if (idx >= 0) overdueCustomers[idx].sent_today = true;
                    }
                    showStatus('danger', msg);
                } finally {
                    renderModal();
                    renderOverdueTable();
                }
            });

            modalTbody.addEventListener('input', (e) => {
                const target = e.target;
                if (!(target instanceof HTMLElement)) return;
                if (target.classList.contains('overdue-next-followup')) {
                    const customerId = target.dataset.customerId;
                    if (!customerId) return;
                    queueOverdueFollowupSave(customerId, { next_followup: target.value || '' });
                }
                if (target.classList.contains('overdue-collection-notes')) {
                    const customerId = target.dataset.customerId;
                    if (!customerId) return;
                    queueOverdueFollowupSave(customerId, { collection_notes: target.value || '' });
                }
            });

            renderModal();
            modal.show();
        };

        overdueExpandBtn?.addEventListener('click', openOverdueModal);
        renderOverdueTable();

        if (customerPaymentForm) {
            customerPaymentForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const customerId = customerPaymentCustomerId?.value;
                if (!customerId) return;
                const url = recordPaymentUrlFor(customerId);
                if (!url) return;
                if (customerPaymentSubmit) {
                    customerPaymentSubmit.disabled = true;
                    customerPaymentSubmit.textContent = 'Recording...';
                }
                try {
                    const formData = new FormData(customerPaymentForm);
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                        body: formData,
                    });
                    const data = await resp.json().catch(() => ({}));
                    if (!resp.ok || data.status !== 'success') throw new Error(data.message || 'Unable to record payment.');
                    customerPaymentModal?.hide();
                    const idx = overdueCustomers.findIndex(r => String(r.customer_id) === String(customerId));
                    if (idx >= 0) {
                        overdueCustomers[idx].balance_due = Number(data.outstanding_after || 0);
                        overdueCustomers[idx].outstanding_due = Number(data.outstanding_after || 0);
                        if (Number(data.overdue_after || 0) <= 0.009) overdueCustomers.splice(idx, 1);
                    }
                    renderOverdueTable();
                    if (customerPaymentSuccessMsg) customerPaymentSuccessMsg.textContent = data.message || 'Payment recorded.';
                    if (customerPaymentSuccessRows) {
                        const rows = (data.allocations || []).map(a => {
                            const statusLabel = (a.status === 'paid') ? 'Paid' : (a.status === 'partial' ? 'Partially paid' : 'Pending');
                            const invoiceUrl = a.invoice_id ? invoiceDetailUrlFor(a.invoice_id) : '';
                            const invoiceLabel = a.invoice_number || '';
                            const invoiceCell = invoiceUrl
                                ? `<a href="${invoiceUrl}" target="_blank" rel="noopener" class="text-decoration-none">${invoiceLabel}</a>`
                                : `${invoiceLabel}`;
                            return `
                                <tr>
                                    <td>${invoiceCell}</td>
                                    <td class="text-end">${currencyFmt(a.applied)}</td>
                                    <td>${statusLabel}</td>
                                    <td class="text-end">${currencyFmt(a.balance_remaining)}</td>
                                </tr>`;
                        }).join('') || '<tr><td colspan="4" class="text-muted text-center py-3">No allocations.</td></tr>';
                        customerPaymentSuccessRows.innerHTML = rows;
                    }
                    if (customerPaymentStatementButtons) {
                        const links = data.statement_links || {};
                        const emailUrl = data.statement_email_url || '';
                        const mkBtnGroup = (key, label) => {
                            const group = links[key] || {};
                            return `
                                <div class="border rounded p-2">
                                    <div class="fw-semibold mb-2">${label}</div>
                                    <div class="d-flex gap-2 flex-wrap">
                                        <a class="btn btn-sm btn-outline-primary" href="${group.download || '#'}">Download</a>
                                        <a class="btn btn-sm btn-outline-secondary" href="${group.print || '#'}" target="_blank" rel="noopener">Print</a>
                                        <button type="button" class="btn btn-sm btn-outline-success js-statement-email" data-email-url="${emailUrl}" data-invoice-type="${key}">Email</button>
                                    </div>
                                </div>`;
                        };
                        customerPaymentStatementButtons.innerHTML = [
                            mkBtnGroup('paid', 'Paid'),
                            mkBtnGroup('pending', 'Pending'),
                            mkBtnGroup('all', 'All'),
                            mkBtnGroup('overdue', 'Overdue'),
                        ].join('');
                    }
                    customerPaymentSuccessModal?.show();
                } catch (err) {
                    showStatus('danger', err.message || 'Unable to record payment.');
                } finally {
                    if (customerPaymentSubmit) {
                        customerPaymentSubmit.disabled = false;
                        customerPaymentSubmit.textContent = 'Record Payment';
                    }
                }
            });
        }

        customerPaymentSuccessModalEl?.addEventListener('click', async (e) => {
            const btn = e.target.closest('.js-statement-email');
            if (!btn) return;
            const emailUrl = btn.getAttribute('data-email-url') || '';
            const invoiceType = btn.getAttribute('data-invoice-type') || 'pending';
            if (!emailUrl) return;
            btn.disabled = true;
            const original = btn.textContent;
            btn.textContent = 'Sending...';
            try {
                const resp = await fetch(emailUrl, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ invoice_type: invoiceType }),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(data.error || data.message || 'Unable to send statement email.');
                showStatus('success', data.message || 'Statement email sent.');
            } catch (err) {
                showStatus('danger', err.message || 'Unable to send statement email.');
            } finally {
                btn.disabled = false;
                btn.textContent = original;
            }
        });
    }

    const onlineOrdersPanel = document.getElementById('online-orders-panel');
    const onlineOrdersTable = document.getElementById('online-orders-table');
    const onlineOrdersTbody = document.getElementById('online-orders-tbody');
    const onlineOrdersEmpty = document.getElementById('online-orders-empty');
    const onlineOrdersCount = document.getElementById('online-orders-count');
    const onlineOrdersModeCount = document.getElementById('online-orders-count-mode');
    const approvalsList = document.getElementById('customer-approvals-list');
    const approvalsEmpty = document.getElementById('customer-approvals-empty');
    const approvalsCount = document.getElementById('customer-approvals-count');
    const orderItemsModalEl = document.getElementById('onlineOrderItemsModal');
    const orderItemsBody = document.getElementById('online-order-items-body');
    const orderItemsMeta = document.getElementById('online-order-items-meta');
    const orderItemsModal = orderItemsModalEl && window.bootstrap ? new bootstrap.Modal(orderItemsModalEl) : null;

    let onlineOrders = [];
    let pendingApprovals = [];
    try {
        const rawOrders = JSON.parse(document.getElementById('parts-online-orders-data')?.textContent || '[]');
        onlineOrders = normalizeToArray(rawOrders);
    } catch (e) {
        onlineOrders = [];
    }
    try {
        const rawApprovals = JSON.parse(document.getElementById('parts-customer-approvals-data')?.textContent || '[]');
        pendingApprovals = normalizeToArray(rawApprovals);
    } catch (e) {
        pendingApprovals = [];
    }
    let onlineOrdersTotal = Number(onlineOrdersCount?.textContent || onlineOrders.length || 0);
    let approvalsTotal = Number(approvalsCount?.textContent || pendingApprovals.length || 0);

    const orderDetailUrlFor = (orderId) => (onlineOrdersPanel?.dataset.invoiceDetailUrlTemplate || '').replace('/0/', `/${orderId}/`);
    const orderStatusUrlFor = (orderId) => (onlineOrdersPanel?.dataset.statusUrlTemplate || '').replace('/0/', `/${orderId}/`);
    const orderCancelUrlFor = (orderId) => (onlineOrdersPanel?.dataset.cancelUrlTemplate || '').replace('/0/', `/${orderId}/`);

    const orderStatusClass = {
        new: 'order-status-new',
        ready: 'order-status-ready',
        picked: 'order-status-picked',
    };

    const formatQty = (value) => {
        const num = Number(value);
        if (!Number.isFinite(num)) return '0';
        const rounded = Math.round(num * 100) / 100;
        if (Number.isInteger(rounded)) return String(rounded);
        return String(rounded);
    };

    const showOrderItems = (order) => {
        if (!orderItemsModalEl || !orderItemsBody || !orderItemsMeta) {
            showStatus('danger', 'Unable to show items right now.');
            return;
        }
        const invoiceNumber = order.invoice_number ? `#${order.invoice_number}` : 'Order';
        const customerName = order.customer_name || 'Customer';
        orderItemsMeta.textContent = `${invoiceNumber} - ${customerName}`;
        const items = Array.isArray(order.items) ? order.items : [];
        if (!items.length) {
            orderItemsBody.innerHTML = '<tr><td colspan="5" class="text-muted text-center py-2">No items found.</td></tr>';
        } else {
            orderItemsBody.innerHTML = items.map((item) => {
                const labelText = escapeHtml(item.label || 'Item');
                const skuText = escapeHtml(item.sku || '');
                const displayLabel = skuText ? `${labelText} (SKU: ${skuText})` : labelText;
                const qty = escapeHtml(formatQty(item.qty));
                const locationText = escapeHtml(item.location || '-');
                const stockLeftRaw = Number(item.stock_left_after ?? item.stock_left);
                const stockLeftText = Number.isFinite(stockLeftRaw) ? String(stockLeftRaw) : '-';
                const imageUrl = item.image_url ? escapeHtml(item.image_url) : '';
                const imageCell = imageUrl
                    ? `<img class="order-item-thumb" src="${imageUrl}" alt="${labelText}">`
                    : '<div class="order-item-thumb order-item-thumb--empty">No image</div>';
                return `<tr><td>${imageCell}</td><td class="text-end">${qty}</td><td>${displayLabel}</td><td>${locationText}</td><td class="text-end">${stockLeftText}</td></tr>`;
            }).join('');
        }
        if (orderItemsModal) {
            orderItemsModal.show();
        } else {
            showStatus('danger', 'Unable to open items modal.');
        }
    };

    const buildOrderRow = (order, highlightIds) => {
        const orderId = order.id || '';
        const invoiceNumber = order.invoice_number || '';
        const customerName = order.customer_name || 'Customer';
        const rawLineCount = Number(order.line_count);
        let lineCount = Number.isFinite(rawLineCount)
            ? rawLineCount
            : (Array.isArray(order.items) ? order.items.length : 0);
        if (!Number.isFinite(lineCount) || lineCount < 0) lineCount = 0;
        const itemsLabel = `${lineCount} item${lineCount === 1 ? '' : 's'}`;
        const statusValue = String(order.status || 'new').toLowerCase();
        const statusLabel = order.status_label || (statusValue.charAt(0).toUpperCase() + statusValue.slice(1));
        const statusClass = orderStatusClass[statusValue] || orderStatusClass.new;
        const placedAt = formatDateTime(order.created_at || order.date);
        const totalAmount = currencyFmt(order.total_amount || 0);
        const viewUrl = orderDetailUrlFor(orderId);
        const rowClass = highlightIds && highlightIds.has(String(orderId)) ? 'order-row--new' : '';

        let actionBtn = '<span class="text-muted small">Picked</span>';
        if (statusValue === 'new') {
            actionBtn = `
                <button type="button" class="btn btn-sm btn-outline-primary order-action-btn js-online-order-action"
                    data-order-id="${orderId}" data-next-status="ready">Mark ready</button>`;
        } else if (statusValue === 'ready') {
            actionBtn = `
                <button type="button" class="btn btn-sm btn-outline-success order-action-btn js-online-order-action"
                    data-order-id="${orderId}" data-next-status="picked">Mark picked</button>`;
        }

        return `
            <tr class="${rowClass}">
                <td>
                    <a class="item-title text-decoration-none" href="${viewUrl}">#${escapeHtml(invoiceNumber)}</a>
                    <div class="item-sub">${escapeHtml(customerName)}</div>
                </td>
                <td>
                    <div class="d-flex align-items-center gap-2 flex-wrap">
                        <div class="order-item-preview">${itemsLabel}</div>
                        <button type="button" class="btn btn-sm btn-outline-secondary js-online-order-items"
                            data-order-id="${orderId}">View items</button>
                    </div>
                </td>
                <td>${placedAt}</td>
                <td><span class="order-status-pill ${statusClass}">${escapeHtml(statusLabel)}</span></td>
                <td class="text-end">${totalAmount}</td>
                <td class="text-end">
                    <div class="d-flex gap-2 justify-content-end flex-wrap">
                        <a class="btn btn-sm btn-outline-secondary order-action-btn" href="${viewUrl}" target="_blank" rel="noopener">View</a>
                        <button type="button" class="btn btn-sm btn-outline-danger order-action-btn js-online-order-cancel"
                            data-order-id="${orderId}">Cancel</button>
                        ${actionBtn}
                    </div>
                </td>
            </tr>`;
    };

    const renderOnlineOrders = (orders, highlightIds = new Set()) => {
        if (!onlineOrdersTbody) return;
        const items = Array.isArray(orders) ? orders : [];
        if (!items.length) {
            onlineOrdersTbody.innerHTML = '';
            onlineOrdersTable?.classList.add('d-none');
            onlineOrdersEmpty?.classList.remove('d-none');
        } else {
            onlineOrdersTbody.innerHTML = items.map(order => buildOrderRow(order, highlightIds)).join('');
            onlineOrdersTable?.classList.remove('d-none');
            onlineOrdersEmpty?.classList.add('d-none');
        }
        const countValue = Number.isFinite(onlineOrdersTotal) ? onlineOrdersTotal : items.length;
        if (onlineOrdersCount) onlineOrdersCount.textContent = countValue;
        if (onlineOrdersModeCount) onlineOrdersModeCount.textContent = countValue;
    };

    const renderApprovals = (approvals, highlightIds = new Set()) => {
        if (!approvalsList) return;
        const items = Array.isArray(approvals) ? approvals : [];
        if (!items.length) {
            approvalsList.innerHTML = '';
            approvalsEmpty?.classList.remove('d-none');
        } else {
            const csrfToken = getCsrfToken();
            approvalsList.innerHTML = items.map((customer) => {
                const rowClass = highlightIds.has(String(customer.id)) ? 'order-row--new' : '';
                const email = customer.email ? customer.email : 'No email on file';
                const requestedAt = formatShortDate(customer.requested_at);
                return `
                    <div class="list-item ${rowClass}">
                        <div>
                            <div class="item-title">${escapeHtml(customer.name || '')}</div>
                            <div class="item-sub">${escapeHtml(email)}</div>
                            <div class="item-sub">Requested ${requestedAt}</div>
                        </div>
                        <div class="item-meta">
                            <form method="post" action="${escapeHtml(customer.approve_url || '#')}" class="js-approval-form">
                                <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(csrfToken)}">
                                <button type="submit" class="btn btn-sm btn-success">Approve</button>
                            </form>
                        </div>
                    </div>`;
            }).join('');
            approvalsEmpty?.classList.add('d-none');
        }
        if (approvalsCount) approvalsCount.textContent = Number.isFinite(approvalsTotal) ? approvalsTotal : items.length;
    };

    const trackNewIds = (previousItems, nextItems) => {
        const prevIds = new Set((previousItems || []).map(item => String(item.id)));
        const newIds = new Set();
        (nextItems || []).forEach((item) => {
            const id = String(item.id);
            if (id && !prevIds.has(id)) newIds.add(id);
        });
        return newIds;
    };

    if (onlineOrdersPanel || approvalsList) {
        renderOnlineOrders(onlineOrders);
        renderApprovals(pendingApprovals);
    }

    onlineOrdersTbody?.addEventListener('click', async (e) => {
        const itemsBtn = e.target.closest('.js-online-order-items');
        if (itemsBtn) {
            const orderId = itemsBtn.dataset.orderId;
            if (!orderId) return;
            const order = onlineOrders.find(item => String(item.id) === String(orderId));
            if (!order) {
                showStatus('danger', 'Unable to load order items.');
                return;
            }
            showOrderItems(order);
            return;
        }
        const cancelBtn = e.target.closest('.js-online-order-cancel');
        if (cancelBtn) {
            const orderId = cancelBtn.dataset.orderId;
            if (!orderId) return;
            if (!window.confirm('Cancel this order? This will delete the invoice.')) return;
            const url = orderCancelUrlFor(orderId);
            if (!url) return;
            cancelBtn.disabled = true;
            const originalLabel = cancelBtn.textContent;
            cancelBtn.textContent = 'Canceling...';
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.status !== 'success') throw new Error(data.message || 'Unable to cancel order.');
                onlineOrders = onlineOrders.filter(item => String(item.id) !== String(orderId));
                if (Number.isFinite(onlineOrdersTotal) && onlineOrdersTotal > 0) {
                    onlineOrdersTotal -= 1;
                }
                renderOnlineOrders(onlineOrders);
                showStatus('success', data.message || 'Order canceled.');
            } catch (err) {
                showStatus('danger', err.message || 'Unable to cancel order.');
            } finally {
                cancelBtn.disabled = false;
                cancelBtn.textContent = originalLabel;
            }
            return;
        }
        const btn = e.target.closest('.js-online-order-action');
        if (!btn) return;
        const orderId = btn.dataset.orderId;
        const nextStatus = btn.dataset.nextStatus;
        if (!orderId || !nextStatus) return;
        const url = orderStatusUrlFor(orderId);
        if (!url) return;
        btn.disabled = true;
        const originalLabel = btn.textContent;
        btn.textContent = 'Updating...';
        try {
            const formData = new FormData();
            formData.append('status', nextStatus);
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                body: formData,
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.status !== 'success') throw new Error(data.message || 'Unable to update order.');
            if (nextStatus === 'picked') {
                onlineOrders = onlineOrders.filter(item => String(item.id) !== String(orderId));
                if (Number.isFinite(onlineOrdersTotal) && onlineOrdersTotal > 0) {
                    onlineOrdersTotal -= 1;
                }
            } else if (data.online_order) {
                const idx = onlineOrders.findIndex(item => String(item.id) === String(orderId));
                if (idx >= 0) onlineOrders[idx] = data.online_order;
            }
            renderOnlineOrders(onlineOrders);
            showStatus('success', 'Order updated.');
        } catch (err) {
            showStatus('danger', err.message || 'Unable to update order.');
        } finally {
            btn.disabled = false;
            btn.textContent = originalLabel;
        }
    });

    approvalsList?.addEventListener('submit', async (e) => {
        const form = e.target.closest('.js-approval-form');
        if (!form) return;
        e.preventDefault();
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalLabel = submitBtn ? submitBtn.textContent : '';
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Approving...';
        }
        try {
            const resp = await fetch(form.action, {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
                body: new FormData(form),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.status === 'error') throw new Error(data.message || 'Unable to approve customer.');
            const approvedId = data.customer_id;
            if (approvedId) {
                pendingApprovals = pendingApprovals.filter(item => String(item.id) !== String(approvedId));
                if (Number.isFinite(approvalsTotal) && approvalsTotal > 0) {
                    approvalsTotal -= 1;
                }
            }
            renderApprovals(pendingApprovals);
            showStatus('success', data.message || 'Customer approved.');
        } catch (err) {
            showStatus('danger', err.message || 'Unable to approve customer.');
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = originalLabel;
            }
        }
    });

    const feedUrl = onlineOrdersPanel?.dataset.feedUrl;
    let feedBusy = false;
    const refreshDashboardFeed = async () => {
        if (!feedUrl || feedBusy) return;
        feedBusy = true;
        try {
            const resp = await fetch(feedUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || data.status !== 'success') throw new Error(data.message || 'Unable to refresh dashboard.');
            const nextOrders = normalizeToArray(data.online_orders);
            const nextApprovals = normalizeToArray(data.pending_customer_approvals);
            const newOrderIds = trackNewIds(onlineOrders, nextOrders);
            const newApprovalIds = trackNewIds(pendingApprovals, nextApprovals);
            onlineOrdersTotal = Number(data.online_orders_count || nextOrders.length || 0);
            approvalsTotal = Number(data.pending_customer_approvals_count || nextApprovals.length || 0);
            onlineOrders = nextOrders;
            pendingApprovals = nextApprovals;
            renderOnlineOrders(onlineOrders, newOrderIds);
            renderApprovals(pendingApprovals, newApprovalIds);
            if (newOrderIds.size > 0) {
                showStatus('info', `New online order${newOrderIds.size > 1 ? 's' : ''} received.`);
            }
        } catch (err) {
            console.warn(err);
        } finally {
            feedBusy = false;
        }
    };

    if (feedUrl) {
        refreshDashboardFeed();
        setInterval(() => {
            if (!document.hidden) refreshDashboardFeed();
        }, 5000);
    }

    const salesRaw = JSON.parse(document.getElementById('parts-category-sales-data')?.textContent || '[]');
    const salesData = normalizeToArray(salesRaw).map(item => ({
        label: item.label || item.name || 'Uncategorized',
        value: Number(item.value || item.total || 0),
    })).filter(item => item.value > 0);
    salesData.sort((a, b) => b.value - a.value);

    const salesDonut = document.getElementById('categorySalesDonut');
    const salesLegend = document.getElementById('categorySalesLegend');
    const salesEmpty = document.getElementById('categorySalesEmpty');
    const salesChart = document.getElementById('categorySalesChart');
    const salesHighlight = document.getElementById('categorySalesHighlight');
    const salesTotalValue = document.getElementById('categorySalesTotal');
    const salesTotalDisplay = document.getElementById('categorySalesTotalDisplay');

    if (!salesData.length || salesData.reduce((sum, item) => sum + item.value, 0) <= 0) {
        salesChart?.classList.add('d-none');
        salesEmpty?.classList.remove('d-none');
    } else if (salesDonut && salesLegend) {
        const palette = ['#2563eb', '#0ea5e9', '#22c55e', '#f59e0b', '#ef4444', '#14b8a6', '#64748b'];
        const total = salesData.reduce((sum, item) => sum + item.value, 0);
        if (salesTotalValue) salesTotalValue.textContent = currencyFmt(total);
        if (salesTotalDisplay) salesTotalDisplay.textContent = currencyFmt(total);

        let current = 0;
        const slices = salesData.map((item, idx) => {
            const pct = total ? (item.value / total) * 100 : 0;
            const start = current;
            const end = current + pct;
            current = end;
            return { color: palette[idx % palette.length], start, end, pct };
        });
        const gradient = slices.map(slice => `${slice.color} ${slice.start}% ${slice.end}%`).join(', ');
        salesDonut.style.background = `conic-gradient(${gradient})`;
        salesLegend.innerHTML = salesData.map((item, idx) => {
            const pct = total ? (item.value / total) * 100 : 0;
            const color = palette[idx % palette.length];
            return `
                <div class="legend-item">
                    <span class="legend-dot" style="--dot-color: ${color}"></span>
                    <div class="legend-text">${escapeHtml(item.label)}</div>
                    <div class="legend-meta">${pct.toFixed(1)}% - ${currencyFmt(item.value)}</div>
                </div>`;
        }).join('');
        const topItem = salesData[0];
        if (salesHighlight && topItem) {
            const topPct = total ? (topItem.value / total) * 100 : 0;
            salesHighlight.textContent = `Top category: ${topItem.label} (${topPct.toFixed(1)}%)`;
        }
    }
});
