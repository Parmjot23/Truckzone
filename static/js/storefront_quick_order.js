(() => {
    const form = document.querySelector('[data-quick-order]');
    if (!form) {
        return;
    }

    const suggestUrl = form.getAttribute('data-suggest-url');
    const rowsContainer = form.querySelector('[data-quick-order-rows]');
    const template = document.querySelector('[data-quick-order-template]');
    const addButton = form.querySelector('[data-quick-order-add]');

    const SUGGEST_MIN_CHARS = 2;
    const SUGGEST_LIMIT = 8;
    const SUGGEST_DELAY = 200;

    const debounce = (callback, wait) => {
        let timer = null;
        return (...args) => {
            if (timer) {
                clearTimeout(timer);
            }
            timer = setTimeout(() => {
                timer = null;
                callback(...args);
            }, wait);
        };
    };

    const buildDropdown = (wrap) => {
        let dropdown = wrap.querySelector('.storefront-suggest');
        if (!dropdown) {
            dropdown = document.createElement('div');
            dropdown.className = 'storefront-suggest';
            dropdown.setAttribute('role', 'listbox');
            wrap.appendChild(dropdown);
        }
        return dropdown;
    };

    const renderSuggestions = (dropdown, results) => {
        dropdown.innerHTML = '';
        if (!results.length) {
            const empty = document.createElement('div');
            empty.className = 'storefront-suggest-empty';
            empty.textContent = 'No products found.';
            dropdown.appendChild(empty);
            dropdown.classList.add('is-open');
            return;
        }

        results.forEach((item) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'storefront-suggest-item quick-order-suggest-item';
            if (item.stock_label && item.stock_label.toLowerCase().includes('out of stock')) {
                button.classList.add('is-disabled');
            }
            button.dataset.productId = item.id;
            button.dataset.productName = item.name || '';
            button.dataset.productSku = item.sku || '';
            button.dataset.productBrand = item.brand || '';
            button.dataset.stockLabel = item.stock_label || '';

            const media = document.createElement('div');
            media.className = 'storefront-suggest-media';
            if (item.image) {
                const img = document.createElement('img');
                img.src = item.image;
                img.alt = item.name || 'Product';
                img.loading = 'lazy';
                media.appendChild(img);
            } else {
                const icon = document.createElement('i');
                icon.className = 'fas fa-box-open';
                media.appendChild(icon);
            }

            const body = document.createElement('div');
            body.className = 'storefront-suggest-body';

            const title = document.createElement('div');
            title.className = 'storefront-suggest-title';
            title.textContent = item.name || 'Product';
            body.appendChild(title);

            const metaParts = [];
            if (item.sku) {
                metaParts.push(`#${item.sku}`);
            }
            if (item.brand) {
                metaParts.push(item.brand);
            }
            if (item.category) {
                metaParts.push(item.category);
            }
            if (metaParts.length) {
                const meta = document.createElement('div');
                meta.className = 'storefront-suggest-meta';
                meta.textContent = metaParts.join(' | ');
                body.appendChild(meta);
            }

            if (item.stock_label) {
                const stock = document.createElement('div');
                stock.className = 'storefront-suggest-meta';
                stock.textContent = item.stock_label;
                body.appendChild(stock);
            }

            button.appendChild(media);
            button.appendChild(body);
            dropdown.appendChild(button);
        });

        dropdown.classList.add('is-open');
    };

    const initRow = (row) => {
        const input = row.querySelector('[data-quick-order-search]');
        const productInput = row.querySelector('[data-quick-order-product-id]');
        const selected = row.querySelector('[data-quick-order-selected]');
        const wrap = row.querySelector('[data-quick-order-search-wrap]');
        const dropdown = wrap ? buildDropdown(wrap) : null;
        let controller = null;

        if (input && dropdown && suggestUrl) {
            const runSuggest = debounce(async () => {
                const query = input.value.trim();
                dropdown.classList.remove('is-loading');
                if (query.length < SUGGEST_MIN_CHARS) {
                    dropdown.innerHTML = '';
                    dropdown.classList.remove('is-open');
                    return;
                }

                dropdown.classList.add('is-open');
                dropdown.classList.add('is-loading');
                dropdown.innerHTML = '<div class="storefront-suggest-loading">Searching...</div>';

                if (controller) {
                    controller.abort();
                }
                controller = new AbortController();

                try {
                    const url = new URL(suggestUrl, window.location.origin);
                    url.searchParams.set('q', query);
                    url.searchParams.set('limit', String(SUGGEST_LIMIT));

                    const response = await fetch(url.toString(), {
                        signal: controller.signal,
                        headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    });
                    if (!response.ok) {
                        throw new Error('Quick order suggest failed');
                    }
                    const payload = await response.json();
                    const results = Array.isArray(payload?.results) ? payload.results : [];
                    dropdown.classList.remove('is-loading');
                    renderSuggestions(dropdown, results);
                } catch (err) {
                    if (err.name === 'AbortError') {
                        return;
                    }
                    dropdown.classList.remove('is-loading');
                    dropdown.innerHTML = '<div class="storefront-suggest-empty">Suggestions unavailable.</div>';
                    dropdown.classList.add('is-open');
                }
            }, SUGGEST_DELAY);

            input.addEventListener('input', () => {
                if (productInput) {
                    productInput.value = '';
                }
                if (selected) {
                    selected.textContent = '';
                    selected.hidden = true;
                }
                runSuggest();
            });

            input.addEventListener('focus', () => {
                if (dropdown.children.length) {
                    dropdown.classList.add('is-open');
                }
            });

            input.addEventListener('blur', () => {
                setTimeout(() => dropdown.classList.remove('is-open'), 200);
            });

            dropdown.addEventListener('click', (event) => {
                const button = event.target.closest('.quick-order-suggest-item');
                if (!button || button.classList.contains('is-disabled')) {
                    return;
                }
                const name = button.dataset.productName || '';
                const sku = button.dataset.productSku || '';
                const label = sku ? `${name} (#${sku})` : name;
                if (input) {
                    input.value = label;
                }
                if (productInput) {
                    productInput.value = button.dataset.productId || '';
                }
                if (selected) {
                    selected.textContent = button.dataset.stockLabel
                        ? `${label} - ${button.dataset.stockLabel}`
                        : label;
                    selected.hidden = false;
                }
                dropdown.classList.remove('is-open');
            });
        }

        const qtyInput = row.querySelector('[data-quick-order-qty-input]');
        row.querySelectorAll('[data-quick-order-qty]').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (!qtyInput) {
                    return;
                }
                const current = parseInt(qtyInput.value || '1', 10);
                const next = btn.dataset.quickOrderQty === 'up' ? current + 1 : current - 1;
                qtyInput.value = Math.max(1, next);
            });
        });

        const removeBtn = row.querySelector('[data-quick-order-remove]');
        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                const rows = rowsContainer.querySelectorAll('[data-quick-order-row]');
                if (rows.length > 1) {
                    row.remove();
                    return;
                }
                if (input) {
                    input.value = '';
                }
                if (productInput) {
                    productInput.value = '';
                }
                if (qtyInput) {
                    qtyInput.value = '1';
                }
                if (selected) {
                    selected.textContent = '';
                    selected.hidden = true;
                }
            });
        }
    };

    const addRow = () => {
        if (!template || !rowsContainer) {
            return;
        }
        const clone = template.content.cloneNode(true);
        const row = clone.querySelector('[data-quick-order-row]');
        rowsContainer.appendChild(clone);
        if (row) {
            initRow(row);
        }
    };

    if (addButton) {
        addButton.addEventListener('click', addRow);
    }

    if (rowsContainer) {
        rowsContainer.querySelectorAll('[data-quick-order-row]').forEach(initRow);
    }
})();
