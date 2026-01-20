# Mobile UI Testing Guide

## Quick Test - Use Chrome DevTools

### Step 1: Open DevTools Mobile View
1. Open your website in Chrome
2. Press `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac)
3. Click the device toggle icon or press `Ctrl+Shift+M`
4. Select a mobile device from the dropdown (e.g., iPhone 12 Pro)

### Step 2: Test Navigation Menu

**Test: Menu Opens and Closes**
1. Click the menu toggle button (wrench icon)
   - ✅ Menu should slide in from the side
   - ✅ Background should be overlaid/dimmed
   - ✅ Page content should not scroll

2. Click the X button inside the menu
   - ✅ Menu should close smoothly

3. Open menu again, click outside the menu
   - ✅ Menu should close

4. Open menu again, press Escape key
   - ✅ Menu should close

5. Open menu, click a navigation link
   - ✅ Menu should close and navigate to the page

### Step 3: Test Grid Layout

**Test: Cards Stay Visible on Scroll**
1. Go to Home page
2. Scroll down slowly
   - ✅ Service cards should remain visible
   - ✅ No cards should disappear or flicker
   - ✅ Hero stats should stay in place

3. Go to Services page
4. Scroll through all services
   - ✅ All service detail cards should be visible
   - ✅ No jumping or shifting content

5. Go to About page
6. Scroll through team cards
   - ✅ Team member cards should not disappear
   - ✅ Certification cards should remain stable

### Step 4: Test Touch Targets

**Test: Buttons Are Easy to Tap**
1. Try tapping various buttons
   - ✅ All buttons should be at least 48x48 pixels
   - ✅ No accidental taps on nearby elements
   - ✅ Clear visual feedback on tap

2. Test form inputs (Contact page)
   - ✅ Input fields should be easy to tap
   - ✅ No zoom-in on iOS when focusing inputs
   - ✅ Labels should be clear and readable

### Step 5: Test Different Screen Sizes

**Test on Multiple Breakpoints**
1. Set viewport to 320px width (iPhone SE)
   - ✅ Content should fit without horizontal scroll
   - ✅ Buttons should stack vertically
   - ✅ Text should be readable

2. Set viewport to 375px width (iPhone 12)
   - ✅ Layout should be comfortable
   - ✅ No overlapping elements

3. Set viewport to 768px width (iPad Portrait)
   - ✅ Some elements may show 2 columns
   - ✅ Navigation should still be mobile version

4. Set viewport to 992px width (iPad Landscape)
   - ✅ Desktop navigation should appear
   - ✅ Multi-column layouts should work

### Step 6: Test Scroll Behavior

**Test: Smooth Scrolling**
1. Scroll slowly from top to bottom
   - ✅ No content disappears
   - ✅ No flickering or jumping
   - ✅ Hero section remains stable

2. Scroll quickly (fling gesture)
   - ✅ All content remains visible
   - ✅ No layout shifts

3. Scroll back to top
   - ✅ Scroll-to-top button appears after scrolling down
   - ✅ WhatsApp button appears
   - ✅ Both buttons work correctly

## Common Issues to Check

### Issue: Menu Won't Close
- **Check**: Is JavaScript enabled?
- **Check**: Are there any console errors?
- **Fix**: Hard refresh (Ctrl+Shift+R)

### Issue: Content Disappears
- **Check**: Is mobile_fixes.css loading?
- **Check**: View page source and verify the CSS link is there
- **Fix**: Clear cache and reload

### Issue: Buttons Too Small
- **Check**: Are you testing on the correct viewport size?
- **Check**: Is mobile_fixes.css loading?
- **Fix**: Verify file path in base.html

### Issue: Horizontal Scrolling
- **Check**: Any images or elements wider than viewport?
- **Fix**: Add `overflow-x: hidden` to specific sections

## Real Device Testing

### iOS Devices (iPhone/iPad)
1. Open Safari
2. Navigate to your site
3. Test all the steps above
4. **Special checks for iOS:**
   - Input fields shouldn't zoom when focused
   - Scroll should feel smooth (not janky)
   - Menu overlay should prevent background scroll

### Android Devices
1. Open Chrome Mobile
2. Navigate to your site
3. Test all the steps above
4. **Special checks for Android:**
   - Touch targets should be comfortable
   - Menu animation should be smooth
   - No lag during scroll

## Performance Testing

### Use Lighthouse
1. Open Chrome DevTools
2. Go to "Lighthouse" tab
3. Select "Mobile" device
4. Check "Performance" and "Accessibility"
5. Run audit
6. **Target Scores:**
   - Performance: 80+
   - Accessibility: 90+
   - Best Practices: 90+

### Expected Results:
- ✅ No layout shifts (CLS close to 0)
- ✅ Fast input responsiveness
- ✅ Smooth animations

## Quick Command to Start Server

```bash
# If you need to start the development server:
cd /workspace
python3 manage.py runserver 0.0.0.0:8000
```

Then open in browser: `http://localhost:8000`

## Pages to Test

Priority order:
1. ✅ **Home** - `/` - Main landing page
2. ✅ **Services** - `/services/` - Service cards grid
3. ✅ **About** - `/about/` - Team cards and mission
4. ✅ **Contact** - `/contact/` - Form inputs and touch targets
5. **Products** - `/store/products/` - Product grid
6. **Booking** - `/booking/` - Booking form
7. **Emergency** - `/emergency/` - Emergency form

## Checklist for Each Page

For every page, verify:
- [ ] Menu opens and closes correctly
- [ ] All content visible while scrolling
- [ ] No horizontal scrolling
- [ ] Buttons are easy to tap
- [ ] Text is readable
- [ ] Images load correctly
- [ ] Forms work (if applicable)
- [ ] Links work
- [ ] Footer is visible and formatted correctly

## Success Criteria

All fixes are successful if:
1. ✅ Navigation menu works flawlessly
2. ✅ No content disappears on scroll
3. ✅ All touch targets are 48x48px minimum
4. ✅ No horizontal scrolling on any page
5. ✅ Smooth performance (no lag or jank)
6. ✅ Content stacks properly on mobile
7. ✅ Forms are usable on mobile

## If Problems Persist

1. **Clear Browser Cache**
   ```
   Chrome: Ctrl+Shift+Delete → Clear cached images and files
   Safari: Settings → Safari → Clear History and Website Data
   ```

2. **Hard Refresh**
   ```
   Chrome: Ctrl+Shift+R (Windows) / Cmd+Shift+R (Mac)
   Safari: Cmd+Option+R
   ```

3. **Check Console Errors**
   - Open DevTools Console tab
   - Look for red error messages
   - Screenshot and report any errors

4. **Verify Files Are Loading**
   - Open DevTools Network tab
   - Reload page
   - Verify these files load with 200 status:
     - mobile_fixes.css
     - landing_page.css
     - responsive_enhancements.css
     - ui_enhancements.js

## Report Template

If issues found, use this template:

```
**Device/Browser**: iPhone 12 / Safari 15
**Page**: Home page
**Issue**: Cards disappear when scrolling
**Steps to Reproduce**:
1. Open home page
2. Scroll to services section
3. Continue scrolling down

**Expected**: All cards remain visible
**Actual**: Service cards disappear
**Screenshot**: [attach screenshot]
**Console Errors**: [paste any errors]
```

---

**Last Updated**: September 30, 2025
**Created By**: AI Assistant
**Version**: 1.0