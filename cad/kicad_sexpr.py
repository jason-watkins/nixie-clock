"""Reader for KiCad's s-expression files: .kicad_pcb, .kicad_mod, .kicad_sym,
fp-lib-table and sym-lib-table.

parse(text) returns nested lists. Every parenthesised form becomes a list whose
first element is its tag; atoms are strings; a quoted string loses its quotes
and backslash escapes. Numbers stay strings, and the caller converts the fields
it reads. kids(), kid() and kidval() pick children by tag.

The case model (cad/case) reads pcb/face/face.kicad_pcb through this module,
and the kicad-fp skill script imports it too, so the format is read in one
place.
"""


def parse(text: str):
    """The single top-level form in text, as nested lists."""
    i, n = 0, len(text)
    stack = [[]]
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            stack[-1].append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            stack[-1].append(text[i:j])
            i = j
    if len(stack) != 1 or not stack[0]:
        raise ValueError("malformed s-expression input")
    return stack[0][0]


def kids(node, tag):
    """Every child form of node whose tag is tag."""
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def kid(node, tag):
    """The first child form of node whose tag is tag, or None."""
    k = kids(node, tag)
    return k[0] if k else None


def kidval(node, tag, default=""):
    """The first atom after the tag of the first child form tagged tag."""
    k = kid(node, tag)
    return k[1] if k and len(k) > 1 else default
