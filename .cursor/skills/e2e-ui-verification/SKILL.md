---
name: e2e-ui-verification
description: Perform exhaustive end-to-end browser verification of UI components, Excel-style table filters, sorting, toggles, modals, layout stability, and overflow/clipping. Use whenever adding, modifying, or testing frontend features.
---

# Exhaustive E2E UI Verification

## Workflow

Copy and complete this checklist for every UI feature verification:

```
E2E Verification Progress:
- [ ] 1. Lock browser tab and record initial live state & modal/container bounding boxes
- [ ] 2. Exercise every filter control (search, dropdowns, checkboxes, Temizle, Tümünü Seç, Arananları Seç)
- [ ] 3. Check geometry & clipping in edge states (0 rows / 1 row): modal height must not collapse, open dropdowns must not be clipped by container overflow
- [ ] 4. Take a screenshot during the edge state (e.g. after Temizle) and visually inspect it
- [ ] 5. Exercise every sort header (asc -> desc -> default)
- [ ] 6. Exercise row actions / toggles in both directions (e.g. Gizliye Al -> Aktif Et) and verify side effects
- [ ] 7. Exercise global reset / Filtreleri Temizle button
- [ ] 8. Restore initial live state, close temporary modals, and unlock browser
```

## React Input & Event Dispatching in CDP

When driving React 18 controlled inputs via `Runtime.evaluate`, always use the native value setter so React's synthetic event system registers the change:

```javascript
const setReactInput = (el, val) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, val);
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

const setReactSelect = (el, val) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(el, val);
  el.dispatchEvent(new Event('change', { bubbles: true }));
};
```

## Mandatory Geometry & Clipping Assertion Snippet

Run this check whenever testing modals, tables, and dropdown menus:

```javascript
const checkGeometry = () => {
  const modal = document.querySelector('.manifest-modal');
  const dropdown = document.querySelector('.excel-dropdown');
  const mRect = modal?.getBoundingClientRect();
  const dRect = dropdown?.getBoundingClientRect();
  return {
    modalHeight: mRect ? Math.round(mRect.height) : 0,
    dropdownHeight: dRect ? Math.round(dRect.height) : 0,
    isDropdownClippedBottom: mRect && dRect ? dRect.bottom > mRect.bottom : false,
    isDropdownClippedRight: mRect && dRect ? dRect.right > mRect.right : false,
  };
};
```

- `modalHeight` when `0 rows` are shown MUST equal `modalHeight` when `1000+ rows` are shown.
- `isDropdownClippedBottom` and `isDropdownClippedRight` MUST be `false`.
