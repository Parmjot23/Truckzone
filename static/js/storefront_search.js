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
        const fragment = document.createDocumentFragment();
        const results = Array.isArray(payload?.results) ? payload.results : [];
        const categories = Array.isArray(payload?.categories) ? payload.categories : [];

        if (!results.length && !categories.length) {
            const empty = document.createElement('div');
            empty.className = 'storefront-suggest-empty';
            empty.textContent = 'Browse the full catalog or try a different keyword.';
            fragment.appendChild(empty);
        } else {
            const grid = document.createElement('div');
            grid.className = 'storefront-suggest-grid';

            const categoryCol = document.createElement('div');
            categoryCol.className = 'storefront-suggest-col';
            const categoryHeader = document.createElement('div');
            categoryHeader.className = 'storefront-suggest-section';
            categoryHeader.textContent = 'Categories';
            categoryCol.appendChild(categoryHeader);

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
                categoryCol.appendChild(link);
            });

            if (!categories.length) {
                const fallbackLink = document.createElement('a');
                fallbackLink.className = 'storefront-suggest-item storefront-suggest-category';
                fallbackLink.href =
                    form?.dataset.storefrontCategoryRoot || buildSearchResultsUrl(form, '');

                const media = document.createElement('div');
                media.className = 'storefront-suggest-media';
                const icon = document.createElement('i');
                icon.className = 'fas fa-layer-group';
                media.appendChild(icon);

                const body = document.createElement('div');
                body.className = 'storefront-suggest-body';
                const title = document.createElement('div');
                title.className = 'storefront-suggest-title';
                title.textContent = 'Browse all categories';
                body.appendChild(title);

                fallbackLink.appendChild(media);
                fallbackLink.appendChild(body);
                categoryCol.appendChild(fallbackLink);
            }

            const productCol = document.createElement('div');
            productCol.className = 'storefront-suggest-col';
            const productHeader = document.createElement('div');
            productHeader.className = 'storefront-suggest-section';
            productHeader.textContent = 'Products';
            productCol.appendChild(productHeader);

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

                productCol.appendChild(link);
            });

            if (!results.length) {
                const fallbackLink = document.createElement('a');
                fallbackLink.className = 'storefront-suggest-item';
                fallbackLink.href = buildSearchResultsUrl(form, '');

                const media = document.createElement('div');
                media.className = 'storefront-suggest-media';
                const icon = document.createElement('i');
                icon.className = 'fas fa-boxes-stacked';
                media.appendChild(icon);

                const body = document.createElement('div');
                body.className = 'storefront-suggest-body';
                const title = document.createElement('div');
                title.className = 'storefront-suggest-title';
                title.textContent = 'Browse all products';
                body.appendChild(title);

                fallbackLink.appendChild(media);
                fallbackLink.appendChild(body);
                productCol.appendChild(fallbackLink);
            }

            grid.appendChild(categoryCol);
            grid.appendChild(productCol);
            fragment.appendChild(grid);
        }

        const footer = document.createElement('div');
        footer.className = 'storefront-suggest-footer';
        const resultsLink = document.createElement('a');
        resultsLink.href = buildSearchResultsUrl(form, query);
        resultsLink.textContent = `See all results for "${query}"`;
        footer.appendChild(resultsLink);
        fragment.appendChild(footer);
        dropdown.replaceChildren(fragment);
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
            dropdown.classList.remove('is-loading');
            const existingError = dropdown.querySelector('.storefront-suggest-error');
            if (existingError) {
                existingError.remove();
            }
            if (query.length < SUGGEST_MIN_CHARS) {
                if (query.length) {
                    dropdown.innerHTML = '';
                    const hint = document.createElement('div');
                    hint.className = 'storefront-suggest-empty';
                    hint.textContent = 'Keep typing for suggestions.';
                    dropdown.appendChild(hint);
                    dropdown.classList.add('is-open');
                } else {
                    dropdown.innerHTML = '';
                    dropdown.classList.remove('is-open');
                }
                return;
            }

            dropdown.classList.add('is-open');
            dropdown.classList.add('is-loading');
            if (!dropdown.children.length) {
                const loading = document.createElement('div');
                loading.className = 'storefront-suggest-loading';
                loading.textContent = 'Searching...';
                dropdown.appendChild(loading);
            }

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
                dropdown.classList.remove('is-loading');
                renderSuggestions(dropdown, payload, query, form);
            } catch (err) {
                if (err.name === 'AbortError') {
                    return;
                }
                dropdown.classList.remove('is-loading');
                dropdown.innerHTML = '';
                const error = document.createElement('div');
                error.className = 'storefront-suggest-empty storefront-suggest-error';
                error.textContent = 'Suggestions are unavailable. Press Enter to search.';
                dropdown.appendChild(error);
                dropdown.classList.add('is-open');
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
