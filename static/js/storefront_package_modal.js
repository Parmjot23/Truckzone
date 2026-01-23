(() => {
  const body = document.body;
  let activeModal = null;
  let lastFocused = null;

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

  const markInCart = (productId) => {
    if (!productId) return;
    document
      .querySelectorAll(`[data-cart-slot][data-product-id="${productId}"]`)
      .forEach((slot) => {
        slot.classList.add('is-in-cart');
      });
  };

  const markBundleInCart = (targetId) => {
    if (!targetId) return;
    document
      .querySelectorAll(`[data-package-status="${targetId}"]`)
      .forEach((slot) => {
        slot.classList.add('is-in-cart');
      });
  };

  const triggerPackageConfetti = (modal) => {
    if (!modal || modal.dataset.hasFreeItem !== 'true') {
      return;
    }
    if (typeof window.launchStorefrontConfetti === 'function') {
      window.launchStorefrontConfetti({ originY: 0.35 });
    }
  };

  const openModal = (modal) => {
    if (activeModal && activeModal !== modal) {
      activeModal.classList.remove('is-open');
      activeModal.setAttribute('aria-hidden', 'true');
    }
    lastFocused = document.activeElement;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    body.classList.add('package-deal-open');
    activeModal = modal;
    const focusTarget =
      modal.querySelector('[data-package-close]') ||
      modal.querySelector('.package-deal-dialog');
    focusTarget?.focus();
    triggerPackageConfetti(modal);
  };

  const closeModal = (modal) => {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    body.classList.remove('package-deal-open');
    if (activeModal === modal) {
      activeModal = null;
    }
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
      lastFocused = null;
    }
  };

  const addAllToCart = async (container, button) => {
    if (button.dataset.packageBusy === 'true') {
      return;
    }

    const forms = Array.from(container.querySelectorAll('form[data-add-to-cart]'));
    const eligibleForms = forms.filter((form) => {
      const submitBtn = form.querySelector('[type="submit"]');
      return !submitBtn || !submitBtn.disabled;
    });

    if (!eligibleForms.length) {
      return;
    }

    if (!window.fetch) {
      eligibleForms[0].submit();
      return;
    }

    button.dataset.packageBusy = 'true';
    storeButtonDefaults(button);
    button.disabled = true;
    setButtonLabel(button, button.dataset.loadingLabel || 'Adding bundle...');

    for (const form of eligibleForms) {
      const submitBtn = form.querySelector('[type="submit"]');
      if (submitBtn) {
        storeButtonDefaults(submitBtn);
        submitBtn.disabled = true;
        setButtonLabel(submitBtn, submitBtn.dataset.loadingLabel || 'Adding...');
      }

      const formData = new FormData(form);
      const csrfToken =
        form.querySelector('[name="csrfmiddlewaretoken"]')?.value || '';

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken,
            Accept: 'application/json',
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

        const productId = data?.product_id || form.dataset.productId;
        if (productId) {
          markInCart(String(productId));
        }

        if (submitBtn) {
          setButtonLabel(submitBtn, submitBtn.dataset.successLabel || 'Added');
        }
      } catch (err) {
        if (submitBtn) {
          restoreButton(submitBtn);
          submitBtn.disabled = false;
        }
        restoreButton(button);
        button.disabled = false;
        button.dataset.packageBusy = 'false';
        window.location.href = form.action;
        return;
      }
    }

    markBundleInCart(button.dataset.packageTarget);
    setButtonLabel(button, button.dataset.successLabel || 'Bundle added');
    window.setTimeout(() => {
      restoreButton(button);
      button.disabled = false;
      button.dataset.packageBusy = 'false';
    }, 1400);
  };

  const resolvePackageContainer = (trigger) => {
    const targetId = trigger.dataset.packageTarget;
    if (targetId) {
      const target = document.getElementById(targetId);
      if (target) {
        return target;
      }
    }
    return trigger.closest('[data-package-modal]');
  };

  document.addEventListener('click', (event) => {
    const openTrigger = event.target.closest('[data-package-open]');
    if (openTrigger) {
      const targetId = openTrigger.dataset.packageOpen;
      const modal = targetId ? document.getElementById(targetId) : null;
      if (modal) {
        event.preventDefault();
        openModal(modal);
      }
      return;
    }

    const closeTrigger = event.target.closest('[data-package-close]');
    if (closeTrigger) {
      const modal = closeTrigger.closest('[data-package-modal]');
      if (modal) {
        closeModal(modal);
      }
      return;
    }

    const addAllTrigger = event.target.closest('[data-package-add-all]');
    if (addAllTrigger) {
      const container = resolvePackageContainer(addAllTrigger);
      if (container) {
        event.preventDefault();
        addAllToCart(container, addAllTrigger);
      }
      return;
    }

    if (event.target.matches('[data-package-modal]')) {
      closeModal(event.target);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && activeModal) {
      closeModal(activeModal);
    }
  });
})();
