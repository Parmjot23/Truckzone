(() => {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const initCarousel = (carousel) => {
    const slides = Array.from(carousel.querySelectorAll('[data-hero-slide]'));
    if (slides.length <= 1) {
      return;
    }

    const dotsContainer = carousel.querySelector('[data-hero-dots]');
    const dots = dotsContainer ? Array.from(dotsContainer.querySelectorAll('[data-hero-dot]')) : [];
    let currentIndex = 0;
    let timerId = null;

    const setActive = (index) => {
      slides.forEach((slide, slideIndex) => {
        slide.classList.toggle('is-active', slideIndex === index);
      });
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle('is-active', dotIndex === index);
        dot.setAttribute('aria-pressed', dotIndex === index ? 'true' : 'false');
      });
      currentIndex = index;
    };

    const nextSlide = () => {
      const nextIndex = (currentIndex + 1) % slides.length;
      setActive(nextIndex);
    };

    const start = () => {
      if (prefersReducedMotion || timerId || carousel.matches(':hover')) {
        return;
      }
      timerId = window.setInterval(nextSlide, 5000);
    };

    const stop = () => {
      if (timerId) {
        window.clearInterval(timerId);
        timerId = null;
      }
    };

    dots.forEach((dot) => {
      dot.addEventListener('click', () => {
        const targetIndex = parseInt(dot.dataset.heroDot, 10);
        if (Number.isNaN(targetIndex)) {
          return;
        }
        stop();
        setActive(targetIndex);
        start();
      });
    });

    carousel.addEventListener('mouseenter', stop);
    carousel.addEventListener('mouseleave', start);
    carousel.querySelectorAll('.hero-showcase-card').forEach((card) => {
      card.addEventListener('mouseenter', stop);
      card.addEventListener('mouseleave', start);
    });

    setActive(0);
    start();
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-hero-carousel]').forEach(initCarousel);
  });
})();
