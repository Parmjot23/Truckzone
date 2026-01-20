# 🚀 Quick Reference Card

## Essential Commands

```bash
# Collect static files
python manage.py collectstatic --noinput

# Run dev server
python manage.py runserver

# Clear static and recollect
python manage.py collectstatic --noinput --clear
```

## Required CSS Includes

```html
{% block extra_css %}
    <link rel="stylesheet" href="{% static 'css/landing_page.css' %}">
    <link rel="stylesheet" href="{% static 'css/responsive_enhancements.css' %}">
{% endblock %}
```

## Required JS Include

```html
{% block extra_js %}
    <script src="{% static 'js/ui_enhancements.js' %}"></script>
{% endblock %}
```

## Component Library

### Hero Section
```html
<header class="hero-section hero-modern hero-home">
    <div class="container">
        <div class="row justify-content-center">
            <div class="col-lg-8 text-center">
                <div class="hero-content hero-glass mx-auto">
                    <div class="hero-badge">
                        <i class="fas fa-check"></i>
                        <span>Badge Text</span>
                    </div>
                    <h1>Hero Heading</h1>
                    <p class="hero-subtitle">Subtitle text</p>
                    <p class="hero-description">Description text</p>
                    <div class="hero-buttons">
                        <a href="#" class="btn btn-primary">Primary</a>
                        <a href="#" class="btn btn-outline">Secondary</a>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <div class="hero-curved-bottom"></div>
</header>
```

### Service Card
```html
<div class="service-card text-center p-4">
    <i class="fas fa-truck fa-3x mb-3 text-primary"></i>
    <h4>Service Title</h4>
    <p>Service description goes here</p>
</div>
```

### Feature Item
```html
<div class="feature-item">
    <i class="fas fa-medal fa-2x text-primary mb-3"></i>
    <h4>Feature Title</h4>
    <p>Feature description goes here</p>
</div>
```

### Button Primary
```html
<a href="#" class="btn btn-primary">
    <i class="fas fa-calendar"></i> Button Text
</a>
```

### Button Outline
```html
<a href="#" class="btn btn-outline">
    <i class="fas fa-phone"></i> Button Text
</a>
```

### Service List
```html
<ul class="service-list">
    <li>List item with checkmark</li>
    <li>Another list item</li>
    <li>One more item</li>
</ul>
```

### Contact Card
```html
<div class="contact-card text-center p-4">
    <i class="fas fa-phone fa-3x mb-3 text-primary"></i>
    <h4>Contact Title</h4>
    <p>Contact information</p>
</div>
```

### Form Input
```html
<div class="form-group mb-3">
    <label for="input_id" class="form-label">Label *</label>
    <input type="text" id="input_id" class="form-control" required>
</div>
```

## CSS Variables

### Colors
```css
var(--primary-500)    /* Orange #f97316 */
var(--primary-600)    /* Orange dark */
var(--secondary-500)  /* Teal #14b8a6 */
var(--accent-500)     /* Purple #a855f7 */
var(--neutral-700)    /* Gray dark */
```

### Spacing
```css
var(--space-xs)   /* 0.5rem / 8px */
var(--space-sm)   /* 1rem / 16px */
var(--space-md)   /* 1.5rem / 24px */
var(--space-lg)   /* 2rem / 32px */
var(--space-xl)   /* 3rem / 48px */
```

### Radius
```css
var(--radius-sm)    /* 0.375rem / 6px */
var(--radius-md)    /* 0.5rem / 8px */
var(--radius-lg)    /* 0.75rem / 12px */
var(--radius-xl)    /* 1rem / 16px */
var(--radius-2xl)   /* 1.5rem / 24px */
var(--radius-full)  /* 9999px / pill */
```

### Shadows
```css
var(--shadow-sm)    /* Small shadow */
var(--shadow-md)    /* Medium shadow */
var(--shadow-lg)    /* Large shadow */
var(--shadow-xl)    /* Extra large shadow */
```

## Responsive Classes

### Display
```css
.d-sm-none    /* Hide on small screens */
.d-md-none    /* Hide on medium screens */
.d-lg-none    /* Hide on large screens */
```

### Grid
```html
<div class="row">
    <div class="col-12 col-md-6 col-lg-4">
        <!-- 1 column mobile, 2 tablet, 3 desktop -->
    </div>
</div>
```

## Utility Classes

```css
.text-center      /* Center text */
.mb-4            /* Margin bottom 1.5rem */
.mt-4            /* Margin top 1.5rem */
.p-4             /* Padding all sides 1.5rem */
.mx-auto         /* Margin auto left/right */
```

## Breakpoints

```css
/* Mobile */
@media (max-width: 576px) { }

/* Tablet */
@media (min-width: 577px) and (max-width: 768px) { }

/* Desktop */
@media (min-width: 769px) { }
```

## Testing URLs

```
Home:       http://localhost:8000/
About:      http://localhost:8000/about/
Services:   http://localhost:8000/services/
Contact:    http://localhost:8000/contact/
Booking:    http://localhost:8000/booking/
```

## Common Issues

### Styles not loading?
```bash
python manage.py collectstatic --noinput --clear
```

### JavaScript not working?
Check console for: `✨ UI Enhancements loaded successfully`

### Mobile menu not opening?
Ensure Bootstrap JS is loaded

### Images not showing?
Check static files path and STATIC_URL setting

## Performance Tips

1. Use `loading="lazy"` on images
2. Keep animations under 300ms
3. Use CSS transforms (not position)
4. Minimize DOM manipulation
5. Use passive event listeners

## Accessibility Checklist

- [ ] All images have alt text
- [ ] Buttons have descriptive text
- [ ] Forms have labels
- [ ] Color contrast meets WCAG AA
- [ ] Keyboard navigation works
- [ ] Focus indicators visible

## Browser DevTools

### Test Responsive
```
F12 → Toggle device toolbar (Ctrl+Shift+M)
```

### Check Performance
```
F12 → Lighthouse → Run audit
```

### View Accessibility
```
F12 → Accessibility tab
```

## File Locations

```
CSS:        static/css/landing_page.css
            static/css/responsive_enhancements.css
            
JS:         static/js/ui_enhancements.js

Templates:  templates/public_*.html
            templates/public/*.html
```

## Git Workflow

```bash
# Check status
git status

# Add changes
git add static/css/ static/js/ templates/

# Commit
git commit -m "Enhanced UI for public pages"

# Push
git push origin main
```

## Documentation

- **Full Docs**: UI_ENHANCEMENTS_SUMMARY.md
- **Visual Guide**: VISUAL_IMPROVEMENTS_GUIDE.md
- **Testing**: TESTING_GUIDE.md
- **README**: README_UI_ENHANCEMENTS.md

---

**Keep this card handy for quick reference! 📌**