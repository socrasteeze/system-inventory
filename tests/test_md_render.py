"""Tests for scripts/md_render.py — the docs-viewer markdown converter."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from md_render import md_to_html


class MdRenderTests(unittest.TestCase):
    def test_heading_and_paragraph(self):
        html = md_to_html("# Title\n\nSome **bold** and *italic* text.")
        self.assertIn('<h1 id="title">Title</h1>', html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<em>italic</em>", html)

    def test_code_fence_escapes_and_shields(self):
        html = md_to_html("```\nif x < 3 & y: **not bold**\n```")
        self.assertIn("x &lt; 3 &amp; y", html)
        self.assertIn("**not bold**", html)  # inline md untouched inside fence
        self.assertNotIn("<strong>", html)

    def test_inline_code_shielded_from_bold(self):
        html = md_to_html("Use `a ** b` and `<tag>` carefully.")
        self.assertIn("<code>a ** b</code>", html)
        self.assertIn("<code>&lt;tag&gt;</code>", html)
        self.assertNotIn("<strong>", html)

    def test_table(self):
        html = md_to_html("| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |")
        self.assertIn("<th>A</th>", html)
        self.assertIn("<td>4</td>", html)
        self.assertEqual(html.count("<tr>"), 3)

    def test_nested_list_with_continuation(self):
        md = "- top item\n  continues here\n  - nested item\n- second top"
        html = md_to_html(md)
        self.assertIn("<li>top item continues here</li>", html)
        self.assertEqual(html.count("<ul>"), 2)
        self.assertEqual(html.count("</ul>"), 2)

    def test_ordered_list(self):
        html = md_to_html("1. first\n2. second")
        self.assertIn("<ol>", html)
        self.assertEqual(html.count("<li>"), 2)

    def test_link(self):
        html = md_to_html("See [the docs](https://example.com/x).")
        self.assertIn('<a href="https://example.com/x">the docs</a>', html)

    def test_hr_and_duplicate_heading_ids(self):
        html = md_to_html("## Same\n\n---\n\n## Same")
        self.assertIn("<hr>", html)
        self.assertIn('id="same"', html)
        self.assertIn('id="same-x"', html)

    def test_repo_markdown_renders_balanced(self):
        root = Path(__file__).resolve().parent.parent
        for fname in ("README.md", "CLAUDE.md", "TODO.md", "NOTICE.md"):
            html = md_to_html((root / fname).read_text(encoding="utf-8"))
            for tag in ("ul", "ol", "li", "table", "pre", "p"):
                self.assertEqual(
                    html.count(f"<{tag}>"), html.count(f"</{tag}>"),
                    f"{fname}: unbalanced <{tag}>")
            self.assertNotIn("\x00", html)


if __name__ == "__main__":
    unittest.main()
