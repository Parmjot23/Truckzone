(() => {
  const modal = document.querySelector('[data-flyer-modal]');
  if (!modal) {
    return;
  }

  const openButtons = Array.from(document.querySelectorAll('[data-flyer-open]'));
  const closeButtons = Array.from(modal.querySelectorAll('[data-flyer-close]'));
  const printButton = modal.querySelector('[data-flyer-print]');
  const body = document.body;

  const openModal = () => {
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    body.classList.add('flyer-modal-open');
  };

  const closeModal = () => {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    body.classList.remove('flyer-modal-open');
    body.classList.remove('flyer-print-mode');
  };

  openButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      openModal();
    });
  });

  closeButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      closeModal();
    });
  });

  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-open')) {
      closeModal();
    }
  });

  if (printButton) {
    const handleAfterPrint = () => {
      body.classList.remove('flyer-print-mode');
    };

    window.addEventListener('afterprint', handleAfterPrint);

    printButton.addEventListener('click', (event) => {
      event.preventDefault();
      if (!modal.classList.contains('is-open')) {
        openModal();
      }
      body.classList.add('flyer-print-mode');
      setTimeout(() => {
        window.print();
      }, 50);
    });
  }
})();
