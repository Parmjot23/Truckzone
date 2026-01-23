(() => {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const colors = ['#f59e0b', '#22c55e', '#38bdf8', '#f43f5e', '#a855f7', '#f97316'];

  const resolveNumber = (value, fallback) => (Number.isFinite(value) ? value : fallback);

  const launchStorefrontConfetti = (options = {}) => {
    if (prefersReducedMotion) {
      return;
    }
    if (typeof window.confetti !== 'function') {
      return;
    }

    const originX = resolveNumber(options.originX, 0.5);
    const originY = resolveNumber(options.originY, 0.5);
    const zIndex = resolveNumber(options.zIndex, 1300);
    const scalar = resolveNumber(options.scalar, 1);

    const baseConfig = {
      spread: 75,
      startVelocity: 40,
      decay: 0.9,
      gravity: 1,
      ticks: 180,
      zIndex,
      scalar,
      colors,
      shapes: ['square', 'circle'],
    };

    const leftX = Math.max(0.05, originX - 0.3);
    const rightX = Math.min(0.95, originX + 0.3);
    const centerY = Math.max(0.1, originY - 0.15);

    window.confetti({
      ...baseConfig,
      particleCount: 80,
      origin: { x: leftX, y: originY },
    });

    window.confetti({
      ...baseConfig,
      particleCount: 80,
      origin: { x: rightX, y: originY },
    });

    window.confetti({
      ...baseConfig,
      particleCount: 120,
      origin: { x: originX, y: centerY },
    });
  };

  window.launchStorefrontConfetti = launchStorefrontConfetti;
})();
