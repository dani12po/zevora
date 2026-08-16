# ZEVORA Workspace Design System

> Page-specific guidance may refine layout, but it must not override the palette, typography, geometry, motion, or accessibility rules in this master.

**Project:** ZEVORA Workspace
**Category:** Developer Tool / AI Workspace
**Density:** 8/10, dense operational interface

## Foundation

### Color Tokens

The interface uses neutral charcoal and slate surfaces with a restrained copper precision accent. Bright emerald, generic navy, saturated gradients, and decorative glow are not part of the visual language.

| Token | Value | Usage |
|---|---:|---|
| `--bg` | `#151718` | Application background |
| `--surface` | `#1b1e20` | Sidebar and primary panels |
| `--surface2` | `#222628` | Controls and secondary panels |
| `--surface3` | `#2a2f31` | Hover and selected surfaces |
| `--border` | `#373d3f` | Standard dividers and borders |
| `--border2` | `#4a5254` | Strong borders and scrollbar thumbs |
| `--text` | `#edf0ed` | Primary text |
| `--text2` | `#adb3b0` | Secondary text |
| `--text3` | `#7d8582` | Muted text |
| `--accent` | `#b9825a` | Primary actions and focus |
| `--accent-dim` | `#b9825a24` | Selected and tinted accent surfaces |
| `--accent-hover` | `#c9956d` | Accent hover state |
| `--purple` | `#9b8fa8` | Planning and specialist semantics |
| `--red` | `#c87368` | Errors and destructive actions |
| `--red-dim` | `#c873681c` | Error surface |
| `--yellow` | `#c5a15b` | Warnings and pending states |
| `--yellow-dim` | `#c5a15b1c` | Warning surface |
| `--blue` | `#7896aa` | Cloud and informational states |
| `--blue-dim` | `#7896aa20` | Informational surface |
| `--cyan` | `#70a3a0` | Tool and data semantics |
| `--green` | `#829b82` | Healthy local state and success |
| `--green-dim` | `#829b821c` | Success surface |

Semantic colors must remain desaturated and subordinate to the copper accent. Local state uses muted sage and a square indicator; cloud state uses steel blue and a circular indicator.

### Typography

- Body and heading stack: `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
- Technical stack: `'JetBrains Mono', 'IBM Plex Mono', 'Cascadia Code', Consolas, monospace`
- Use the technical stack for gateway and status pills, file paths, model/provider identifiers, command text, usage values, token counts, costs, dates in tables, and other tabular numeric data.
- Use tabular numerals for values that users compare vertically.
- Letter spacing is `0`; do not scale font sizes with viewport width.

Load Inter at weights 400-700 and JetBrains Mono at weights 400-600.

### Geometry

| Token | Value | Usage |
|---|---:|---|
| `--radius-sm` | `4px` | Badges, compact controls, scrollbar thumbs |
| `--radius` | `6px` | Panels, dialogs, inputs, buttons |

Do not exceed a 6px radius. Cards are reserved for individual repeated records or genuinely framed tools; page sections remain unframed.

### Motion

- Standard interaction and route timing: `160ms ease-out`.
- Route entry may fade from opacity 0 and translate vertically by no more than 3px.
- Hover states must not resize or shift layout.
- Under `prefers-reduced-motion: reduce`, disable animation and transition duration.

### Scrollbars

Use thin themed scrollbars. Tracks use `--surface`; thumbs use `--border2` with a 4px radius and change to `--text3` on hover.

## Components

- Primary buttons use `--accent`; hover uses `--accent-hover`.
- Secondary controls use neutral surfaces and borders, with copper reserved for focus or active state.
- Inputs use `--surface2`, `--border`, and a visible copper focus border/ring.
- Panels use `--surface` or `--surface2`, a 1px neutral border, and 4-6px radii.
- Badges are compact rectangles, not pills, unless the shape communicates a specific binary status.
- Use Lucide-style SVG icons for familiar actions. Do not use emoji as interface icons.
- Empty and loading states that depend on execution location must display a local or cloud indicator.
- Fixed-format controls need stable dimensions so labels, icons, loading text, and dynamic values cannot shift layout.

## Accessibility And Responsive Rules

- Maintain at least 4.5:1 contrast for normal text.
- Every interactive element needs a visible keyboard focus state.
- Pair semantic color with text, icon, shape, or state copy; never rely on color alone.
- Preserve usable layouts at 375px, 768px, 1024px, and 1440px.
- Prevent horizontal page scrolling and content overlap.
- Mobile navigation must have an accessible close control and scrim.
- Respect reduced-motion preferences.

## Forbidden Patterns

- Navy plus bright emerald themes
- Saturated purple/pink gradients or one-hue palettes
- Decorative gradient or bokeh backgrounds
- Radii above 6px
- Nested cards or floating-card page sections
- Emoji used as controls or category icons
- Layout-shifting hover transforms
- Invisible focus states or low-contrast muted text
- Marketing landing-page composition inside the operational workspace

## Delivery Checklist

- [ ] Palette values match `static/styles.css` exactly
- [ ] Inter and JetBrains Mono are loaded
- [ ] Technical values use the mono stack and tabular numerals
- [ ] All radii are 4px or 6px
- [ ] Route and interaction motion is 160ms and reduced-motion safe
- [ ] Local/cloud states are distinguishable without color alone
- [ ] Scrollbars use the neutral theme tokens
- [ ] Keyboard focus and contrast are verified
- [ ] 375px, 768px, 1024px, and 1440px layouts do not overlap or scroll horizontally
