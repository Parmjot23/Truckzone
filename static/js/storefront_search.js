(() => {
    const SUGGEST_MIN_CHARS = 2;
    const SUGGEST_LIMIT = 8;
    const SUGGEST_DELAY = 200;
    const RESULTS_DELAY = 350;

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

    const buildFilterParams = () => {
        const params = new URLSearchParams();
        const filterForm = document.querySelector('[data-storefront-filters]');
        if (!filterForm) {
            return params;
        }
        const multiKeys = new Set(['brand', 'model', 'vin']);
        const formData = new FormData(filterForm);
        for (const [key, value] of formData.entries()) {
            if (!value) {
                continue;
            }
            if (multiKeys.has(key)) {
                params.append(key, value);
            } else if (key.startsWith('attr_')) {
                params.set(key, value);
            }
        }
        return params;
    };

    const buildResultsParams = (page) => {
        const params = new URLSearchParams();
        const multiKeys = new Set(['brand', 'model', 'vin']);
        const filterForm = document.querySelector('[data-storefront-filters]');
        if (filterForm) {
            const formData = new FormData(filterForm);
            for (const [key, value] of formData.entries()) {
                if (!value) {
                    continue;
                }
                if (multiKeys.has(key)) {
                    params.append(key, value);
                } else if (key.startsWith('attr_')) {
                    params.set(key, value);
                }
            }
        }

        const toolbarForm = document.querySelector('[data-storefront-toolbar]');
        if (toolbarForm) {
            const formData = new FormData(toolbarForm);
            for (const [key, value] of formData.entries()) {
                if (!value) {
                    continue;
                }
                if (multiKeys.has(key) || key.startsWith('attr_')) {
                    continue;
                }
                params.set(key, value);
            }
        }

        const searchInput = document.querySelector('[data-storefront-search-sync]');
        if (searchInput) {
            const term = searchInput.value.trim();
            if (term) {
                params.set('q', term);
            } else {
                params.delete('q');
            }
        }
        if (page) {
            params.set('page', page);
        } else {
            params.delete('page');
        }
        return params;
    };

    const syncSearchInputs = (value, sourceInput) => {
        document.querySelectorAll('[data-storefront-search-sync]').forEach((input) => {
            if (input === sourceInput) {
                return;
            }
            input.value = value;
        });
        const filterForm = document.querySelector('[data-storefront-filters]');
        if (filterForm) {
            const hiddenQuery = filterForm.querySelector('input[name="q"]');
            if (hiddenQuery) {
                hiddenQuery.value = value;
            }
        }
    };

    const buildSearchResultsUrl = (form, query) => {
        const action = form?.getAttribute('action') || window.location.pathname;
        const url = new URL(action, window.location.origin);
        const params = new URLSearchParams();
        if (query) {
            params.set('q', query);
        }
        const filterParams = buildFilterParams();
        for (const [key, value] of filterParams.entries()) {
            params.append(key, value);
        }
        url.search = params.toString();
        return url.toString();
    };

    const renderSuggestions = (dropdown, payload, query, form) => {
        dropdown.innerHTML = '';
        const results = Array.isArray(payload?.results) ? payload.results : [];
        const categories = Array.isArray(payload?.categories) ? payload.categories : [];

        if (!results.length && !categories.length) {
            const empty = document.createElement('div');
            empty.className = 'storefront-suggest-empty';
            empty.textContent = `No matches for "${query}".`;
            dropdown.appendChild(empty);
        } else {
            if (categories.length) {
                const categoryHeader = document.createElement('div');
                categoryHeader.className = 'storefront-suggest-section';
                categoryHeader.textContent = 'Categories';
                dropdown.appendChild(categoryHeader);
            }

            categories.forEach((item) => {
                const link = document.createElement('a');
                link.className = 'storefront-suggest-item storefront-suggest-category';
                link.href = item.url || '#';

                const media = document.createElement('div');
                media.className = 'storefront-suggest-media';
                const icon = document.createElement('i');
                icon.className = 'fas fa-folder-open';
                media.appendChild(icon);

                const body = document.createElement('div');
                body.className = 'storefront-suggest-body';

                const title = document.createElement('div');
                title.className = 'storefront-suggest-title';
                title.textContent = item.name || 'Category';
                body.appendChild(title);

                const metaParts = [];
                if (item.path) {
                    metaParts.push(item.path);
                }
                if (item.group) {
                    metaParts.push(item.group);
                }
                if (metaParts.length) {
                    const meta = document.createElement('div');
                    meta.className = 'storefront-suggest-meta';
                    meta.textContent = metaParts.join(' | ');
                    body.appendChild(meta);
                }

                link.appendChild(media);
                link.appendChild(body);
                dropdown.appendChild(link);
            });

            if (results.length) {
                const productHeader = document.createElement('div');
                productHeader.className = 'storefront-suggest-section';
                productHeader.textContent = 'Products';
                dropdown.appendChild(productHeader);
            }

            results.forEach((item) => {
                const link = document.createElement('a');
                link.className = 'storefront-suggest-item';
                link.href = item.url || '#';

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
                title.textContent = item.name || 'Untitled product';
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

                if (item.note) {
                    const note = document.createElement('div');
                    note.className = 'storefront-suggest-meta';
                    note.textContent = item.note;
                    body.appendChild(note);
                }

                link.appendChild(media);
                link.appendChild(body);

                if (item.price) {
                    const price = document.createElement('div');
                    price.className = 'storefront-suggest-price';
                    price.textContent = item.price;
                    if (item.price_badge) {
                        const badge = document.createElement('span');
                        badge.className = 'storefront-suggest-badge';
                        badge.textContent = item.price_badge;
                        price.appendChild(badge);
                    }
                    link.appendChild(price);
                }

                dropdown.appendChild(link);
            });
        }

        const footer = document.createElement('div');
        footer.className = 'storefront-suggest-footer';
        const resultsLink = document.createElement('a');
        resultsLink.href = buildSearchResultsUrl(form, query);
        resultsLink.textContent = `See all results for "${query}"`;
        footer.appendChild(resultsLink);
        dropdown.appendChild(footer);
        dropdown.classList.add('is-open');
    };

    const initSuggestInput = (input) => {
        if (!input || input.dataset.storefrontSuggestReady === 'true') {
            return;
        }
        const form = input.closest('form');
        const suggestUrl = form?.dataset.storefrontSuggestUrl;
        if (!suggestUrl) {
            return;
        }

        const anchor =
            input.closest('.storefront-search-input') ||
            input.closest('.toolbar-search') ||
            input.closest('.storefront-search') ||
            input.parentElement;
        if (!anchor) {
            return;
        }

        let dropdown = anchor.querySelector('.storefront-suggest');
        if (!dropdown) {
            dropdown = document.createElement('div');
            dropdown.className = 'storefront-suggest';
            dropdown.setAttribute('role', 'listbox');
            anchor.appendChild(dropdown);
        }

        let controller = null;

        const runSuggest = debounce(async () => {
            const query = input.value.trim();
            if (query.length < SUGGEST_MIN_CHARS) {
                dropdown.classList.remove('is-open');
                dropdown.innerHTML = '';
                return;
            }

            dropdown.innerHTML = '<div class="storefront-suggest-loading">Searching...</div>';
            dropdown.classList.add('is-open');

            if (controller) {
                controller.abort();
            }
            controller = new AbortController();

            const url = new URL(suggestUrl, window.location.origin);
            url.searchParams.set('q', query);
            url.searchParams.set('limit', String(SUGGEST_LIMIT));

            const filterParams = buildFilterParams();
            for (const [key, value] of filterParams.entries()) {
                url.searchParams.append(key, value);
            }

            try {
                const response = await fetch(url.toString(), {
                    signal: controller.signal,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!response.ok) {
                    throw new Error('Suggestion request failed');
                }
                const payload = await response.json();
                renderSuggestions(dropdown, payload, query, form);
            } catch (err) {
                if (err.name === 'AbortError') {
                    return;
                }
                dropdown.classList.remove('is-open');
                dropdown.innerHTML = '';
            }
        }, SUGGEST_DELAY);

        input.addEventListener('input', runSuggest);
        input.addEventListener('focus', () => {
            if (dropdown.children.length) {
                dropdown.classList.add('is-open');
            }
        });
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                dropdown.classList.remove('is-open');
            }
        });
        input.addEventListener('blur', () => {
            setTimeout(() => dropdown.classList.remove('is-open'), 200);
        });

        input.dataset.storefrontSuggestReady = 'true';
    };

    const initSuggestions = (root = document) => {
        root.querySelectorAll('[data-storefront-search-input]').forEach((input) => {
            initSuggestInput(input);
        });
    };

    const bindDynamicAddToCart = (container) => {
        const forms = container.querySelectorAll('form[data-add-to-cart]');
        if (!forms.length) {
            return;
        }

        const updateCartBadges = (count) => {
            document.querySelectorAll('[data-cart-count]').forEach((el) => {
                el.textContent = count;
            });
        };

        const getButtonTextEl = (button) => button.querySelector('.btn-text');

        const setButtonLabel = (button, label) => {
            const textEl = getButtonTextEl(button);
            if (textEl) {
                textEl.textContent = label;
                button.setAttribute('aria-label', label);
                button.setAttribute('title', label);
                return;
            }
            button.innerHTML = label;
        };

        const storeButtonDefaults = (button) => {
            const textEl = getButtonTextEl(button);
            if (textEl) {
                if (!button.dataset.originalLabel) {
                    button.dataset.originalLabel = textEl.textContent.trim();
                }
                return;
            }
            if (!button.dataset.originalHtml) {
                button.dataset.originalHtml = button.innerHTML;
            }
        };

        const restoreButton = (button) => {
            if (button.dataset.originalLabel) {
                setButtonLabel(button, button.dataset.originalLabel);
                return;
            }
            if (button.dataset.originalHtml) {
                button.innerHTML = button.dataset.originalHtml;
                return;
            }
            button.innerHTML = 'Add to cart';
        };

        forms.forEach((form) => {
            if (form.dataset.storefrontCartBound === 'true') {
                return;
            }
            form.dataset.storefrontCartBound = 'true';

            form.addEventListener('submit', async (event) => {
                if (!window.fetch) {
                    return;
                }
                event.preventDefault();

                const submitBtn = form.querySelector('[type="submit"]');
                if (submitBtn) {
                    storeButtonDefaults(submitBtn);
                    submitBtn.disabled = true;
                    setButtonLabel(submitBtn, submitBtn.dataset.loadingLabel || 'Adding...');
                }

                const formData = new FormData(form);
                const csrfToken = form.querySelector('[name="csrfmiddlewaretoken"]')?.value;

                try {
                    const response = await fetch(form.action, {
                        method: 'POST',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-CSRFToken': csrfToken || '',
                            'Accept': 'application/json',
                        },
                        body: formData,
                    });

                    if (!response.ok) {
                        throw new Error('Add to cart failed');
                    }

                    const data = await response.json();
                    if (data && typeof data.cart_count !== 'undefined') {
                        updateCartBadges(data.cart_count);
                    }
                    if (data && typeof data.product_id !== 'undefined') {
                        const productId = String(data.product_id);
                        document.querySelectorAll(`[data-cart-slot][data-product-id="${productId}"]`).forEach((slot) => {
                            slot.classList.add('is-in-cart');
                        });
                    }

                    if (submitBtn) {
                        setButtonLabel(submitBtn, submitBtn.dataset.successLabel || 'Added');
                    }
                } catch (err) {
                    if (submitBtn) {
                        restoreButton(submitBtn);
                        submitBtn.disabled = false;
                    }
                    form.submit();
                    return;
                }

                if (submitBtn) {
                    setTimeout(() => {
                        submitBtn.disabled = false;
                        restoreButton(submitBtn);
                    }, 1200);
                }
            });
        });
    };

    const initLiveResults = (container) => {
        const toolbarForm = container.querySelector('[data-storefront-toolbar]');
        const filterForm = container.querySelector('[data-storefront-filters]');
        if (!toolbarForm || !filterForm) {
            return;
        }

        let resultsController = null;

        const updateResults = async (page) => {
            const params = buildResultsParams(page);
            params.set('partial', '1');
            const url = `${window.location.pathname}?${params.toString()}`;
            const cleanParams = new URLSearchParams(params);
            cleanParams.delete('partial');
            const cleanUrl = cleanParams.toString()
                ? `${window.location.pathname}?${cleanParams.toString()}`
                : window.location.pathname;

            if (resultsController) {
                resultsController.abort();
            }
            resultsController = new AbortController();
            container.classList.add('storefront-results-loading');

            try {
                const response = await fetch(url, {
                    signal: resultsController.signal,
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!response.ok) {
                    throw new Error('Failed to refresh results');
                }
                const html = await response.text();
                container.innerHTML = html;
                container.classList.remove('storefront-results-loading');
                history.replaceState({}, '', cleanUrl);
                const queryValue = cleanParams.get('q') || '';
                syncSearchInputs(queryValue, null);
                initSuggestions(container);
                bindDynamicAddToCart(container);
            } catch (err) {
                if (err.name === 'AbortError') {
                    return;
                }
                window.location.href = cleanUrl;
            }
        };

        const debouncedUpdate = debounce(() => updateResults(), RESULTS_DELAY);

        if (!container.dataset.storefrontLiveBound) {
            container.addEventListener('change', (event) => {
                const target = event.target;
                if (!target) {
                    return;
                }
                if (target.matches('input[type="checkbox"], select')) {
                    debouncedUpdate();
                }
            });

            container.addEventListener('input', (event) => {
                const target = event.target;
                if (!target || !target.matches('[data-storefront-search-sync]')) {
                    return;
                }
                syncSearchInputs(target.value, target);
                debouncedUpdate();
            });

            container.addEventListener('submit', (event) => {
                const form = event.target;
                if (!form || !form.matches('[data-storefront-toolbar], [data-storefront-filters]')) {
                    return;
                }
                event.preventDefault();
                debouncedUpdate();
            });

            container.addEventListener('click', (event) => {
                const link = event.target.closest('.storefront-page-link');
                if (link && link.tagName === 'A') {
                    event.preventDefault();
                    const linkUrl = new URL(link.href, window.location.origin);
                    const page = linkUrl.searchParams.get('page');
                    updateResults(page);
                    return;
                }
                const viewLink = event.target.closest('.view-toggle a');
                if (viewLink) {
                    event.preventDefault();
                    const viewUrl = new URL(viewLink.href, window.location.origin);
                    const page = viewUrl.searchParams.get('page');
                    const viewValue = viewUrl.searchParams.get('view');
                    if (viewValue) {
                        document.querySelectorAll('input[name="view"]').forEach((input) => {
                            input.value = viewValue;
                        });
                    }
                    const params = new URLSearchParams(viewUrl.search);
                    params.delete('page');
                    history.replaceState({}, '', viewUrl.pathname + (params.toString() ? `?${params.toString()}` : ''));
                    updateResults(page);
                }
            });

            container.dataset.storefrontLiveBound = 'true';
        }

        const topSearchForm = document.querySelector('[data-storefront-search-form]');
        const topSearchInput = document.querySelector('[data-storefront-search-sync][data-storefront-main-search]');
        if (topSearchForm && topSearchInput && !topSearchForm.dataset.storefrontLiveBound) {
            topSearchInput.addEventListener('input', () => {
                syncSearchInputs(topSearchInput.value, topSearchInput);
                debouncedUpdate();
            });
            topSearchForm.addEventListener('submit', (event) => {
                event.preventDefault();
                syncSearchInputs(topSearchInput.value, topSearchInput);
                debouncedUpdate();
            });
            topSearchForm.dataset.storefrontLiveBound = 'true';
        }
    };

    const init = () => {
        initSuggestions(document);
        bindDynamicAddToCart(document);
        const resultsContainer = document.querySelector('[data-storefront-results]');
        if (resultsContainer) {
            initLiveResults(resultsContainer);
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
