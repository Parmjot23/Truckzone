# Mobile Navigation Testing Guide

## Quick Visual Test

### ✅ What You Should See Now

#### 1. **On Page Load (Mobile < 768px)**
```
┌─────────────────────────────────┐
│  [Logo]                         │
│    🔧                           │  ← Hamburger button visible
└─────────────────────────────────┘
```

#### 2. **After Scrolling Down**
```
┌─────────────────────────────────┐
│                            🔧   │  ← Only hamburger visible (fixed top-right)
└─────────────────────────────────┘
```

#### 3. **When Menu Opened (Before Scroll)**
```
┌─────────────────────────────────┐
│  [Logo]                         │
│    🔧                           │
│                                 │
│  ┌───────────────────────────┐ │
│  │                      ✕    │ │  ← Close button
│  │                           │ │
│  │   🏠 Home                │ │
│  │   ℹ️  About               │ │
│  │   🔧 Services            │ │
│  │   🏪 Products            │ │
│  │   📞 Contact             │ │
│  │                           │ │
│  └───────────────────────────┘ │
└─────────────────────────────────┘
```

#### 4. **When Menu Opened (After Scroll)**
```
┌─────────────────────────────────┐
│                            🔧   │  ← Hamburger still visible
│  ┌───────────────────────────┐ │
│  │                      ✕    │ │  ← Close button
│  │                           │ │
│  │   🏠 Home                │ │
│  │   ℹ️  About               │ │
│  │   🔧 Services            │ │
│  │   🏪 Products            │ │
│  │   📞 Contact             │ │
│  │                           │ │
│  └───────────────────────────┘ │
└─────────────────────────────────┘
```

## Step-by-Step Testing

### Test 1: Initial Visibility ✓
1. Open the website on mobile (or resize browser to < 768px width)
2. **Expected:** See the logo and hamburger menu button
3. **Pass if:** Both logo and hamburger (🔧 wrench icon) are visible

### Test 2: Scroll Behavior ✓
1. Scroll down the page
2. **Expected:** Logo disappears, hamburger button stays fixed at top-right
3. **Pass if:** Hamburger button remains visible and clickable

### Test 3: Menu Opens ✓
1. Click the hamburger button
2. **Expected:** Menu slides down with gradient background
3. **Pass if:** 
   - Menu appears smoothly
   - All 5 navigation items visible
   - Close (✕) button visible in top-right of menu
   - Background is slightly blurred
   - Body scroll is disabled

### Test 4: Menu Items Visible ✓
1. With menu open, check all items
2. **Expected:** See all items with icons:
   - 🏠 Home
   - ℹ️  About
   - 🔧 Services
   - 🏪 Products
   - 📞 Contact
3. **Pass if:** All items are visible and readable

### Test 5: Close Button Works ✓
1. Click the ✕ button in menu
2. **Expected:** Menu closes smoothly
3. **Pass if:** Menu disappears and background scroll re-enabled

### Test 6: Click Outside Closes ✓
1. Open menu
2. Click anywhere outside the menu area
3. **Expected:** Menu closes
4. **Pass if:** Menu closes when clicking outside

### Test 7: ESC Key Closes ✓
1. Open menu
2. Press ESC key on keyboard
3. **Expected:** Menu closes
4. **Pass if:** Menu closes

### Test 8: Navigation Works ✓
1. Open menu
2. Click "About" link
3. **Expected:** Navigate to About page and menu closes
4. **Pass if:** Page navigates and menu auto-closes

### Test 9: Scrolled State Menu ✓
1. Scroll down so navbar is in scrolled state
2. Click hamburger button
3. **Expected:** Menu still opens properly
4. **Pass if:** Menu appears from correct position with all items

### Test 10: Menu Doesn't Overflow ✓
1. Open menu on very small screen (320px width)
2. **Expected:** Menu fits on screen with scroll if needed
3. **Pass if:** Menu is contained within viewport

## Device-Specific Tests

### iPhone (375px - 428px)
- [ ] Menu button visible
- [ ] Menu opens full width
- [ ] All items accessible
- [ ] Smooth animations
- [ ] No horizontal scroll

### Android Phone (360px - 412px)
- [ ] Menu button visible
- [ ] Menu opens properly
- [ ] Touch targets adequate (48px min)
- [ ] No layout shifts

### Tablet Portrait (768px - 1024px)
- [ ] Hamburger menu still shown (< 992px)
- [ ] Menu overlay works
- [ ] Larger touch targets

### Small Devices (320px - 360px)
- [ ] Menu button not too small
- [ ] Menu items stack properly
- [ ] Text is readable
- [ ] No content cut off

## Browser Testing

### iOS Safari
```bash
# Test these scenarios:
1. Portrait mode
2. Landscape mode
3. With/without scroll
4. Menu open/close
5. Navigation works
```

### Chrome Mobile
```bash
# Test these scenarios:
1. DevTools mobile emulation
2. Actual device
3. Different zoom levels
4. Accessibility features on
```

### Firefox Mobile
```bash
# Test these scenarios:
1. Standard mode
2. Reader mode compatibility
3. Private browsing
```

## Common Issues & Solutions

### ❌ Menu Button Not Visible
**Check:**
- Is viewport width < 992px?
- Is z-index sufficient (should be 1200)?
- Is display set to flex?

**Fix:**
- Check browser console for CSS errors
- Verify mobile_fixes.css is loaded
- Clear browser cache

### ❌ Menu Doesn't Open
**Check:**
- Is JavaScript enabled?
- Any console errors?
- Is `navbarToggler` found by JavaScript?

**Fix:**
- Hard refresh (Ctrl+Shift+R)
- Check network tab for failed resources
- Verify script is loaded after DOM elements

### ❌ Menu Items Not Visible
**Check:**
- Is `.navbar-collapse.show` applied?
- Are items hidden by z-index?
- Is display: block set on .show?

**Fix:**
- Inspect element in DevTools
- Check computed styles
- Verify CSS cascade isn't overriding

### ❌ Menu Positioned Wrong
**Check:**
- Top, left, right values
- Position: fixed is applied
- Viewport units are calculated correctly

**Fix:**
- Adjust top/left/right in CSS
- Check for transform issues
- Verify parent positioning

## Performance Testing

### Load Time
- [ ] Menu responds within 100ms
- [ ] No layout shift (CLS < 0.1)
- [ ] Smooth 60fps animation

### Interaction
- [ ] Touch target ≥ 48px
- [ ] No accidental clicks
- [ ] Immediate visual feedback

### Memory
- [ ] No memory leaks on open/close
- [ ] Event listeners properly cleaned
- [ ] No zombie event handlers

## Accessibility Testing

### Screen Reader
- [ ] Menu button announced correctly
- [ ] Menu state (expanded/collapsed) announced
- [ ] Menu items are focusable
- [ ] Tab order is logical

### Keyboard Navigation
- [ ] Tab to menu button
- [ ] Enter/Space opens menu
- [ ] Tab through menu items
- [ ] ESC closes menu
- [ ] Focus returns to button

### Color Contrast
- [ ] Menu items meet WCAG AA (4.5:1)
- [ ] Focus indicators visible
- [ ] Hover states clear

## Checklist Summary

Print this and check off as you test:

```
📱 MOBILE NAVIGATION TESTING

Initial State:
□ Logo visible on load
□ Hamburger button visible
□ Navbar sticky positioned

Scroll Behavior:
□ Hamburger stays visible when scrolled
□ Logo hides on scroll (optional)
□ No layout jump

Menu Opening:
□ Click hamburger opens menu
□ Menu slides in smoothly
□ Close button visible
□ All 5 nav items visible
□ Background scroll disabled

Menu Interaction:
□ Click close button works
□ Click outside closes menu
□ ESC key closes menu
□ Menu items are clickable
□ Navigation works

Different States:
□ Works before scroll
□ Works after scroll
□ Works on very small screens
□ Works on tablets < 992px

Responsive:
□ iPhone size (375px)
□ Android size (360px)
□ Small phones (320px)
□ Tablets (768-991px)

Browsers:
□ Safari iOS
□ Chrome Mobile
□ Firefox Mobile
□ Samsung Internet

Accessibility:
□ Screen reader compatible
□ Keyboard navigable
□ Sufficient contrast
□ Focus indicators
```

## Quick Debug Commands

If testing in browser DevTools:

```javascript
// Check if menu elements exist
console.log('Toggler:', document.getElementById('navbarToggler'));
console.log('Menu:', document.getElementById('navbarNav'));
console.log('Close:', document.getElementById('mobileMenuClose'));

// Check if menu is showing
console.log('Has show class:', 
  document.getElementById('navbarNav').classList.contains('show'));

// Check viewport width
console.log('Viewport width:', window.innerWidth);
console.log('Is mobile:', window.innerWidth < 992);

// Test toggle function
navbarToggler.click(); // Should toggle menu
```

## Success Criteria

✅ **All tests passed when:**
- Menu button always visible on mobile
- Menu opens/closes smoothly
- All navigation items accessible
- Works across all test devices
- No console errors
- Meets accessibility standards
- Performance is smooth

---

**Need Help?**
- Review MOBILE_NAVIGATION_FIX.md for technical details
- Check browser console for errors
- Test in real devices, not just emulators
- Compare with desktop version (≥ 992px) to see differences