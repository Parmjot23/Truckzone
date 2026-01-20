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
