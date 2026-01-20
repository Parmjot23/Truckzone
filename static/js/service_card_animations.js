document.addEventListener('DOMContentLoaded', () => {
  const serviceCards = document.querySelectorAll('.service-card');

  if (!serviceCards.length) {
    return;
  }

  const HIDDEN_LEFT = 'is-hidden-left';
  const HIDDEN_RIGHT = 'is-hidden-right';
  const VISIBLE = 'is-visible';

  const getOrientation = (card) => (card.classList.contains('service-card--right') ? 'right' : 'left');

  const setHiddenState = (card, side) => {
    card.classList.remove(HIDDEN_LEFT, HIDDEN_RIGHT, VISIBLE);
    if (side === 'right') {
      card.classList.add(HIDDEN_RIGHT);
    } else {
      card.classList.add(HIDDEN_LEFT);
    }
  };

  const revealCard = (card) => {
    card.classList.remove(HIDDEN_LEFT, HIDDEN_RIGHT);
    card.classList.add(VISIBLE);
  };

  // Initialise with the default orientation-based hidden state
  serviceCards.forEach((card) => {
    const orientation = getOrientation(card);
    setHiddenState(card, orientation);
  });

  let lastKnownScrollY = window.scrollY;
  let scrollDirection = 'down';

  window.addEventListener(
    'scroll',
    () => {
      const currentY = window.scrollY;
      scrollDirection = currentY > lastKnownScrollY ? 'down' : 'up';
      lastKnownScrollY = currentY;
    },
    { passive: true }
  );

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const card = entry.target;
        const orientation = getOrientation(card);

        if (entry.isIntersecting) {
          window.requestAnimationFrame(() => revealCard(card));
          return;
        }

        // Determine the off-screen side based on scroll direction
        const hideToSide = (() => {
          if (scrollDirection === 'down') {
            return orientation;
          }
          return orientation === 'right' ? 'left' : 'right';
        })();

        window.requestAnimationFrame(() => setHiddenState(card, hideToSide));
      });
    },
    {
      threshold: 0.35,
      rootMargin: '0px 0px -10% 0px',
    }
  );

  serviceCards.forEach((card) => observer.observe(card));
});
