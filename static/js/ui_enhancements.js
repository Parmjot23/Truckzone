/**
 * UI Enhancements JavaScript
 * Adds smooth interactions and animations to public pages
 * Version: 1.0
 */

(function() {
    'use strict';

    // ========================================================================
    // Intersection Observer for Fade-in Animations
    // ========================================================================
    
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const fadeInObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const el = entry.target;
                el.classList.add('animate-on-scroll');
                // Ensure element remains visible after animation
                el.addEventListener('animationend', () => {
                    el.style.opacity = '1';
                    el.style.transform = 'none';
                    el.classList.remove('will-animate');
                }, { once: true });
                // Unobserve after animation to improve performance
                fadeInObserver.unobserve(el);
            }
        });
    }, observerOptions);

    // Observe elements for fade-in animation (disabled on mobile to prevent disappearing)
    const animateElements = () => {
        // Skip animations on mobile to prevent disappearing content
        if (window.innerWidth <= 768) {
            return;
        }
        
        const elements = document.querySelectorAll(
            '.service-card, .feature-item, .mission-card, .team-card, ' +
            '.contact-card, .service-detail-card, .certification-card, ' +
            '.emergency-card, .about-image'
        );
        
        elements.forEach(el => {
            // Mark element as ready for animation and hide it until it becomes visible
            if (!el.classList.contains('will-animate')) {
                el.classList.add('will-animate');
            }

            fadeInObserver.observe(el);
        });
    };

    // ========================================================================
    // Lazy Loading Images
    // ========================================================================
    
    const lazyLoadImages = () => {
        const images = document.querySelectorAll('img[loading="lazy"]');
        
        const imageObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.classList.add('loaded');
                    imageObserver.unobserve(img);
                }
            });
        });
        
        images.forEach(img => imageObserver.observe(img));
    };

    // ========================================================================
    // Scroll Progress Indicator
    // ========================================================================
    
    const createScrollProgress = () => {
        // Create progress bar element
        const progressBar = document.createElement('div');
        progressBar.className = 'scroll-progress';
        progressBar.innerHTML = '<div class="scroll-progress-bar"></div>';
        document.body.appendChild(progressBar);

        // Update progress on scroll
        const updateProgress = () => {
            const windowHeight = document.documentElement.scrollHeight - window.innerHeight;
            const scrolled = (window.pageYOffset / windowHeight) * 100;
            const progressBarEl = document.querySelector('.scroll-progress-bar');
            if (progressBarEl) {
                progressBarEl.style.width = Math.min(scrolled, 100) + '%';
            }
        };

        window.addEventListener('scroll', updateProgress, { passive: true });
    };

    // Add CSS for scroll progress
    const addScrollProgressStyles = () => {
        if (!document.getElementById('scroll-progress-styles')) {
            const style = document.createElement('style');
            style.id = 'scroll-progress-styles';
            style.textContent = `
                .scroll-progress {
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    height: 4px;
                    background: rgba(0, 0, 0, 0.05);
                    z-index: 9999;
                    pointer-events: none;
                }
                .scroll-progress-bar {
                    height: 100%;
                    background: linear-gradient(90deg, var(--primary-500), var(--accent-500));
                    width: 0%;
                    transition: width 0.1s ease-out;
                }
            `;
            document.head.appendChild(style);
        }
    };

    // ========================================================================
    // Smooth Anchor Scrolling
    // ========================================================================
    
    const setupSmoothScrolling = () => {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                const href = this.getAttribute('href');
                if (href === '#' || href === '') return;
                
                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    const offsetTop = target.offsetTop - 100; // Account for fixed header
                    
                    window.scrollTo({
                        top: offsetTop,
                        behavior: 'smooth'
                    });
                }
            });
        });
    };

    // ========================================================================
    // Form Input Enhancements
    // ========================================================================
    
    const enhanceFormInputs = () => {
        const inputs = document.querySelectorAll('.form-control, .form-select');
        
        inputs.forEach(input => {
            // Add floating label effect
            const handleInput = () => {
                if (input.value) {
                    input.classList.add('has-value');
                } else {
                    input.classList.remove('has-value');
                }
            };
            
            input.addEventListener('input', handleInput);
            input.addEventListener('change', handleInput);
            
            // Initial check
            handleInput();
        });
    };

    // ========================================================================
    // Parallax Effect for Hero Images (disabled on mobile)
    // ========================================================================
    
    const setupParallax = () => {
        // Skip on mobile to prevent visual issues
        if (window.innerWidth <= 768) {
            return;
        }
        
        const heroSections = document.querySelectorAll('.hero-section');
        
        const handleScroll = () => {
            heroSections.forEach(hero => {
                const scrolled = window.pageYOffset;
                const rate = scrolled * 0.3;
                
                const heroFigures = hero.querySelectorAll('.hero-side-figure');
                heroFigures.forEach((figure, index) => {
                    const direction = index % 2 === 0 ? 1 : -1;
                    figure.style.transform = `translateY(${rate * direction}px)`;
                });
            });
        };
        
        if (heroSections.length > 0) {
            window.addEventListener('scroll', handleScroll, { passive: true });
        }
    };

    // ========================================================================
    // Feature Image Pulse Animation
    // ========================================================================

    const setupFeatureImageSequence = () => {
        const featureImages = Array.from(
            document.querySelectorAll('.feature-item--visual .feature-item__image')
        );

        if (!featureImages.length) {
            return;
        }

        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return;
        }

        featureImages.forEach((img, index) => {
            img.dataset.featureSequence = String(index);
            img.dataset.featureAnimationState = 'idle';

            img.addEventListener(
                'animationend',
                (event) => {
                    if (event.animationName !== 'feature-image-pulse') {
                        return;
                    }

                    img.classList.remove('feature-item__image--pulsing');
                    img.style.removeProperty('--feature-image-delay');
                    img.dataset.featureAnimationState = 'cooldown';
                }
            );
        });

        const observer = new IntersectionObserver(
            (entries) => {
                const sortedEntries = entries.slice().sort((a, b) => {
                    const aIndex = Number(a.target.dataset.featureSequence || 0);
                    const bIndex = Number(b.target.dataset.featureSequence || 0);
                    return aIndex - bIndex;
                });

                sortedEntries.forEach((entry) => {
                    const img = entry.target;
                    const state = img.dataset.featureAnimationState;

                    if (entry.isIntersecting) {
                        if (state !== 'idle') {
                            return;
                        }

                        const sequence = Number(img.dataset.featureSequence || 0);
                        const delay = Math.max(sequence * 140, 0);
                        img.style.setProperty('--feature-image-delay', `${delay}ms`);
                        img.dataset.featureAnimationState = 'running';

                        window.requestAnimationFrame(() => {
                            img.classList.add('feature-item__image--pulsing');
                        });
                        return;
                    }

                    if (state === 'idle') {
                        return;
                    }

                    img.dataset.featureAnimationState = 'idle';
                    img.classList.remove('feature-item__image--pulsing');
                    img.style.removeProperty('--feature-image-delay');
                });
            },
            {
                threshold: 0.55,
                rootMargin: '0px 0px -15% 0px',
            }
        );

        featureImages.forEach((img) => observer.observe(img));
    };

    // ========================================================================
    // Card Tilt Effect (Desktop Only)
    // ========================================================================

    const setupCardTilt = () => {
        if (window.innerWidth < 768) return; // Skip on mobile
        
        const cards = document.querySelectorAll('.service-card, .feature-item');
        
        cards.forEach(card => {
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;
                
                const rotateX = (y - centerY) / 20;
                const rotateY = (centerX - x) / 20;
                
                card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-8px)`;
            });
            
            card.addEventListener('mouseleave', () => {
                card.style.transform = '';
            });
        });
    };

    // ========================================================================
    // Scroll Button Enhancement
    // ========================================================================

    const enhanceScrollButton = () => {
        const scrollBtn = document.getElementById('scrollUp');

        if (!scrollBtn) {
            return;
        }

        const updateButtonVisibility = () => {
            const show = window.pageYOffset > 300;
            scrollBtn.style.display = show ? 'flex' : 'none';

            if (show) {
                scrollBtn.style.animation = 'fadeInUp 0.3s ease-out';
            }
        };

        window.addEventListener('scroll', updateButtonVisibility, { passive: true });
        updateButtonVisibility();
    };

    // ========================================================================
    // Mobile Menu Enhancement
    // ========================================================================

    const enhanceMobileMenu = () => {
        const toggler = document.querySelector('.custom-toggler');
        const navCollapse = document.querySelector('.navbar-collapse');

        if (!(toggler && navCollapse)) {
            return;
        }

        const updateMenuStyles = () => {
            const isExpanded = navCollapse.classList.contains('show');

            navCollapse.style.transition = 'opacity 0.3s ease-out';
            // Clear any inline sizing that could prevent the menu from opening
            navCollapse.style.maxHeight = '';

            if (isExpanded) {
                navCollapse.style.opacity = '1';
                toggler.setAttribute('aria-expanded', 'true');
            } else {
                navCollapse.style.opacity = '';
                toggler.setAttribute('aria-expanded', 'false');
            }
        };

        // Observe class changes triggered by the inline navigation script
        const observer = new MutationObserver(() => {
            window.requestAnimationFrame(updateMenuStyles);
        });

        observer.observe(navCollapse, { attributes: true, attributeFilter: ['class'] });

        // Ensure the correct state is applied on load
        updateMenuStyles();
    };

    // ========================================================================
    // Stats Counter Animation
    // ========================================================================
    
    const animateStats = () => {
        const stats = document.querySelectorAll('.hero-stat-number');

        const counterObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) {
                    return;
                }

                const stat = entry.target;
                const originalText = stat.textContent.trim();

                // Only animate values that are simple numbers with an optional suffix
                // e.g. "500+", "100%". Complex values like "24/7" should be left untouched.
                const match = originalText.match(/^(\d[\d,]*)\s*([^\d]*)$/);

                if (!match) {
                    counterObserver.unobserve(stat);
                    stat.textContent = originalText;
                    return;
                }

                const numericPart = match[1];
                const suffix = match[2] || '';
                const targetNumber = parseInt(numericPart.replace(/,/g, ''), 10);

                if (!Number.isFinite(targetNumber) || targetNumber <= 0) {
                    counterObserver.unobserve(stat);
                    stat.textContent = originalText;
                    return;
                }

                const hasThousandsSeparator = numericPart.includes(',');
                let current = 0;
                const increment = Math.max(targetNumber / 50, 1);

                const formatValue = (value) => {
                    const rounded = Math.min(Math.ceil(value), targetNumber);
                    return hasThousandsSeparator
                        ? rounded.toLocaleString()
                        : String(rounded);
                };

                const timer = setInterval(() => {
                    current += increment;

                    if (current >= targetNumber) {
                        stat.textContent = (hasThousandsSeparator
                            ? targetNumber.toLocaleString()
                            : String(targetNumber)) + suffix;
                        clearInterval(timer);
                    } else {
                        stat.textContent = formatValue(current) + suffix;
                    }
                }, 30);

                counterObserver.unobserve(stat);
            });
        }, { threshold: 0.5 });

        stats.forEach(stat => counterObserver.observe(stat));
    };

    // ========================================================================
    // Page Transition Effect
    // ========================================================================
    
    const setupPageTransition = () => {
        // Disabled to prevent any chance of content remaining hidden
        document.body.style.opacity = '1';
        document.body.style.transition = '';
    };

    // ========================================================================
    // Initialize All Enhancements
    // ========================================================================
    
    const init = () => {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        // Check if user prefers reduced motion
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        
        if (!prefersReducedMotion) {
            animateElements();
            setupParallax();
            setupFeatureImageSequence();
            setupCardTilt();
            animateStats();
            setupPageTransition();
        }
        
        // Always enable these (essential functionality)
        lazyLoadImages();
        addScrollProgressStyles();
        createScrollProgress();
        setupSmoothScrolling();
        enhanceFormInputs();
        enhanceScrollButton();
        enhanceMobileMenu();
        
        console.log('✨ UI Enhancements loaded successfully');
    };

    // Start initialization
    init();

})();
