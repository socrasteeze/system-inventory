"""
md_render.py — minimal, deterministic Markdown -> HTML converter.

Covers exactly the constructs this repo's Markdown files use (README.md,
CLAUDE.md, TODO.md, NOTICE.md): ATX headings, fenced code blocks, pipe
tables, nested unordered/ordered lists with hanging-indent continuation
lines, horizontal rules, paragraphs, and the inline set (escaped HTML,
`code`, **bold**, *italic*, [links](url)). No third-party dependency —
the docs viewer must build from a stock Python install like every other
artifact. Not a general-purpose Markdown engine; unknown constructs
degrade to plain paragraphs rather than erroring.
"""
import re

_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*]+?)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^\s*(---+|\*\*\*+)\s*$")
_ULIST = re.compile(r"^(\s*)-\s+(.*)$")
_OLIST = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}.*\|.*$")


def _escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _inline(s):
    """Inline markdown on an already-raw string. Code spans are rendered
    first and shielded with placeholders so bold/italic/link regexes never
    touch their contents (formulas, globs, and snippets live in them)."""
    s = _escape(s)
    shields = []

    def _shield(m):
        shields.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(shields) - 1}\x00"

    s = _CODE_SPAN.sub(_shield, s)
    s = _LINK.sub(r'<a href="\2">\1</a>', s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITALIC.sub(r"<em>\1</em>", s)
    for i, frag in enumerate(shields):
        s = s.replace(f"\x00{i}\x00", frag)
    return s


def _slugify(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-") or "section"


def md_to_html(text):
    """Convert a markdown document to an HTML fragment (no <html> shell)."""
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    seen_ids = set()
    i = 0
    n = len(lines)
    # list_stack entries: (indent, "ul"|"ol")
    list_stack = []

    def close_lists(to_indent=-1):
        while list_stack and list_stack[-1][0] >= to_indent >= 0 or (to_indent < 0 and list_stack):
            ind, kind = list_stack.pop()
            out.append(f"</{kind}>")

    def close_lists_to(indent):
        while list_stack and list_stack[-1][0] > indent:
            _, kind = list_stack.pop()
            out.append(f"</{kind}>")

    while i < n:
        line = lines[i]

        # fenced code block
        if line.lstrip().startswith("```"):
            close_lists()
            code = []
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                code.append(_escape(lines[i]))
                i += 1
            i += 1  # skip closing fence
            out.append("<pre><code>" + "\n".join(code) + "</code></pre>")
            continue

        # blank line: paragraph/list-item boundary (lists stay open across
        # single blanks only if the next line is another list item at depth)
        if not line.strip():
            nxt = lines[i + 1] if i + 1 < n else ""
            if list_stack and (_ULIST.match(nxt) or _OLIST.match(nxt)):
                i += 1
                continue
            close_lists()
            i += 1
            continue

        # heading
        m = _HEADING.match(line)
        if m:
            close_lists()
            level = len(m.group(1))
            body = _inline(m.group(2).strip())
            hid = _slugify(body)
            while hid in seen_ids:
                hid += "-x"
            seen_ids.add(hid)
            out.append(f'<h{level} id="{hid}">{body}</h{level}>')
            i += 1
            continue

        # horizontal rule
        if _HR.match(line) and not list_stack:
            out.append("<hr>")
            i += 1
            continue

        # table: current line has pipes and the next is a separator row
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            close_lists()

            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]

            head = cells(line)
            i += 2
            rows = []
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(cells(lines[i]))
                i += 1
            thead = "".join(f"<th>{_inline(c)}</th>" for c in head)
            tbody = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in rows)
            out.append(f"<table><thead><tr>{thead}</tr></thead>"
                       f"<tbody>{tbody}</tbody></table>")
            continue

        # list item (unordered or ordered)
        mu, mo = _ULIST.match(line), _OLIST.match(line)
        if mu or mo:
            indent = len((mu or mo).group(1))
            kind = "ul" if mu else "ol"
            body = mu.group(2) if mu else mo.group(3)
            close_lists_to(indent)
            if not list_stack or list_stack[-1][0] < indent or list_stack[-1][1] != kind:
                if list_stack and list_stack[-1][0] == indent:
                    _, old = list_stack.pop()
                    out.append(f"</{old}>")
                list_stack.append((indent, kind))
                out.append(f"<{kind}>")
            # hanging-indent continuation lines belong to this item
            item = [body]
            while i + 1 < n:
                nxt = lines[i + 1]
                if (nxt.strip() and not _ULIST.match(nxt) and not _OLIST.match(nxt)
                        and not _HEADING.match(nxt) and not nxt.lstrip().startswith("```")
                        and len(nxt) - len(nxt.lstrip()) > indent):
                    item.append(nxt.strip())
                    i += 1
                else:
                    break
            out.append(f"<li>{_inline(' '.join(item))}</li>")
            i += 1
            continue

        # paragraph: gather until a blank line or block construct
        close_lists()
        para = [line.strip()]
        while i + 1 < n:
            nxt = lines[i + 1]
            if (not nxt.strip() or _HEADING.match(nxt) or _HR.match(nxt)
                    or _ULIST.match(nxt) or _OLIST.match(nxt)
                    or nxt.lstrip().startswith("```")
                    or ("|" in nxt and i + 2 < n and _TABLE_SEP.match(lines[i + 2]))):
                break
            para.append(nxt.strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
        i += 1

    close_lists()
    return "\n".join(out)
