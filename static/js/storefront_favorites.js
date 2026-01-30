(() => {
    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    };

    const updateButtonState = (button, isFavorite) => {
        if (!button) {
            return;
        }
        button.classList.toggle('is-active', isFavorite);
        button.setAttribute('aria-pressed', isFavorite ? 'true' : 'false');
        button.setAttribute(
            'title',
            isFavorite ? 'Remove from favorites' : 'Add to favorites'
        );
        const icon = button.querySelector('i');
        if (icon) {
            icon.classList.toggle('fa-solid', isFavorite);
            icon.classList.toggle('fa-regular', !isFavorite);
        }
    };

    const syncButtons = (productId, isFavorite) => {
        if (!productId) {
            return;
        }
        document
            .querySelectorAll(`[data-favorite-toggle][data-product-id="${productId}"]`)
            .forEach((button) => updateButtonState(button, isFavorite));
    };

    const handleToggle = async (event) => {
        const button = event.target.closest('[data-favorite-toggle]');
        if (!button) {
            return;
        }

        const form = button.closest('form');
        const standaloneUrl = button.getAttribute('data-favorite-url');
        const actionUrl = standaloneUrl || form?.getAttribute('action');
        if (!actionUrl) {
            return;
        }

        event.preventDefault();
        if (button.dataset.loading === 'true') {
            return;
        }

        button.dataset.loading = 'true';
        button.disabled = true;

        const payload = standaloneUrl ? new FormData() : (form ? new FormData(form) : new FormData());

        try {
            const response = await fetch(actionUrl, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken(),
                    'Accept': 'application/json',
                },
                body: payload,
            });
            if (!response.ok) {
                throw new Error('Favorite toggle failed');
            }
            const data = await response.json();
            if (data && typeof data.is_favorite !== 'undefined') {
                const productId = String(data.product_id || button.dataset.productId || '');
                syncButtons(productId, data.is_favorite);
            }
        } catch (err) {
            if (form && !standaloneUrl) {
                form.submit();
            }
        } finally {
            button.disabled = false;
            button.dataset.loading = 'false';
        }
    };

    document.addEventListener('click', handleToggle);
})();
