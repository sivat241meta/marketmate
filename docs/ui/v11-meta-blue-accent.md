# v11: Meta blue accent

Same v9 workspace layout, components and JS hooks — only colours changed
(Task 105, per the owner's "instead of purple use meta blue color theme").

- Accent `--accent` #0866FF (lines, borders, focus rings, tab underline,
  icons, selected outlines), `--accent-ink` #0064E0 (primary buttons,
  accent text), `--accent-soft` #E7F0FF (tints, NEW badge, "new" chips).
- Neutrals: ink #1C2B33, muted #65676B, line #E4E6EB, soft #F0F2F5,
  bg #F7F8FA.
- Dark chrome #1E1F21: active pill #1B2B44 (white text), readable accent
  #4D9BFF.
- The only gradient is the centre mic button:
  `linear-gradient(135deg,#0064E0,#0081FB 55%,#00B2FF)`.
- Logo pair E (default): Meta blue #0866FF + green #1FA34A, "Market" in
  #0064E0, dark variant #4D9BFF — see `docs/brand.md`.

Every text pair passes WCAG AA (≥ 4.5:1); see
`test_text_background_pairs_pass_contrast` in `tests/test_task64.py`.
Older guides (`v9-clickup-workspace.html`, `meta-blue.html`,
`fresh-green.html`, `fresh-market.html`) are kept as design history.
