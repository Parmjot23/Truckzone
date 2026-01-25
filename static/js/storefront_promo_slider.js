(() => {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const initSlider = (slider) => {
    const slides = Array.from(slider.querySelectorAll('[data-promo-slide]'));
    if (!slides.length) {
      return;
    }

    const promoBadge = slider.closest('.storefront-hero-promos')?.querySelector('[data-promo-hero-badge]');
    const dots = Array.from(slider.querySelectorAll('[data-promo-dot]'));
    const prevButton = slider.querySelector('[data-promo-prev]');
    const nextButton = slider.querySelector('[data-promo-next]');
    let currentIndex = slides.findIndex((slide) => slide.classList.contains('is-active'));
    if (currentIndex < 0) {
      currentIndex = 0;
    }
    let timerId = null;

    const updatePromoBadge = (slide) => {
      if (!promoBadge) {
        return;
      }
      const badge = slide.querySelector('.storefront-promo-card-badge');
      promoBadge.textContent = badge ? badge.textContent.trim() : '';
    };

    const setActive = (index) => {
      slides.forEach((slide, slideIndex) => {
        slide.classList.toggle('is-active', slideIndex === index);
      });
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle('is-active', dotIndex === index);
        dot.setAttribute('aria-pressed', dotIndex === index ? 'true' : 'false');
      });
      updatePromoBadge(slides[index]);
      currentIndex = index;
    };

    const nextSlide = () => {
      setActive((currentIndex + 1) % slides.length);
    };

    const prevSlide = () => {
      setActive((currentIndex - 1 + slides.length) % slides.length);
    };

    const start = () => {
      if (prefersReducedMotion || timerId || slides.length <= 1) {
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

    if (prevButton) {
      prevButton.addEventListener('click', () => {
        stop();
        prevSlide();
        start();
      });
    }

    if (nextButton) {
      nextButton.addEventListener('click', () => {
        stop();
        nextSlide();
        start();
      });
    }

    dots.forEach((dot) => {
      dot.addEventListener('click', () => {
        const targetIndex = parseInt(dot.dataset.promoDot, 10);
        if (Number.isNaN(targetIndex)) {
          return;
        }
        stop();
        setActive(targetIndex);
        start();
      });
    });

    slider.addEventListener('mouseenter', stop);
    slider.addEventListener('mouseleave', start);

    setActive(currentIndex);
    start();
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-promo-slider]').forEach(initSlider);
  });
})();
