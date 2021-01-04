"""
Attempt at a multi-pass CST (concrete syntax tree) RST-ish parser.

This does not (and likely will not) support all of RST syntax, and may support
syntax that is not in the rst spec, mostly to support Python docstrings.

Goals
-----

The goal in here is to parse RST while keeping most of the original information
available in order to be able to _fix_ some of them with minimal of no changes
to the rest of the original input. This include but not limited to having
consistent header markers, and whether examples are (or not) indented with
respect to preceding paragraph.

The second goal is flexibility of parsing rules on a per-section basis;
Typically numpy doc strings have a different syntax depending on the section you
are in (Examples, vs Returns, vs Parameters), in what looks like; but is not;
definition list.

This also should be able to parse and give you a ast/cst without knowing ahead
of time the type of directive that are registered.

This will likely be used in the project in two forms, a lenient form that try to
guess as much as possible and suggest update to your style.

A strict form that avoid guessing and give you more, structured data.


Implementation
--------------

The implementation is not meant to be efficient but works in many multiple pass
that refine the structure of the document in order to potentially swapped out
for customisation.

Most of the high level split in sections and block is line-based via the
Line/lines objects that wrap a ``str``, but keep track of the original line
number and indent/dedent operations.


Junk Code
---------

There is possibly a lot of junk code in there due to multiple experiments.

Correctness
-----------

Yep, many things are probably wrong; or parsed incorrectly;

When possible if there is an alternative way in the source rst to change the
format, it's likely the way to go.

Unless your use case is widely adopted it is likely not worse the complexity
"""

from __future__ import annotations
import sys
from typing import List, Tuple, Optional, Union

from papyri.utils import dedent_but_first
from there import print

ex = """
For the most part, direct use of the object-oriented library is encouraged when
programming; pyplot is primarily for working interactively. The exceptions are
the pyplot functions :dummy:`.pyplot.figure`, :domain:role:`.pyplot.subplot`, :also:dir:`.pyplot.subplots`,
and `.pyplot.savefig`, which `` can greatly simplify scripting. An example of verbatim code would be ``1+1 = 2`` but it is
not valid Python assign:: 
"""

# 3x -> 9x for bright
WHAT = lambda x: "\033[36m" + x + "\033[0m"
HEADER = lambda x: "\033[35m" + x + "\033[0m"
BLUE = lambda x: "\033[34m" + x + "\033[0m"
GREEN = lambda x: "\033[32m" + x + "\033[0m"
ORANGE = lambda x: "\033[33m" + x + "\033[0m"
RED = lambda x: "\033[31m" + x + "\033[0m"
ENDC = lambda x: "\033[0m" + x + "\033[0m"
BOLD = lambda x: "\033[1m" + x + "\033[0m"
UNDERLINE = lambda x: "\033[4m" + x + "\033[0m"


base_types = {int, str, bool, type(None)}

from typing import List, Union
from typing import get_type_hints as gth
from functools import lru_cache


@lru_cache
def get_type_hints(type):
    return gth(type)

class Base:
    @classmethod
    def _instance(cls):
        return cls()

    @classmethod
    def _deserialise(cls, **kwargs):
        # print("will deserialise", cls)
        try:
            instance = cls._instance()
        except Exception as e:
            raise type(e)(f"Error deserialising {cls}, {kwargs})") from e
        for k, v in kwargs.items():
            setattr(instance, k, v)
        return instance



def serialize(instance, annotation):
    # print("will serialise", type(instance), "as", annotation)
    try:
        if (annotation in base_types) and (isinstance(instance, annotation)):
            return instance
        elif getattr(annotation, "__origin__", None) is tuple and isinstance(
            instance, tuple
        ):
            # this may be slightly incorrect as usually tuple as positionally type dependant.
            inner_annotation = annotation.__args__
            assert len(inner_annotation) == 1, inner_annotation
            return tuple(serialize(x, inner_annotation[0]) for x in instance)
        elif getattr(annotation, "__origin__", None) is list and isinstance(
            instance, list
        ):
            inner_annotation = annotation.__args__
            assert len(inner_annotation) == 1, inner_annotation
            return [serialize(x, inner_annotation[0]) for x in instance]
        elif getattr(annotation, "__origin__", None) is Union:

            inner_annotation = annotation.__args__
            if len(inner_annotation) == 2 and inner_annotation[1] == type(None):
                assert inner_annotation[0] != None
                # here we are optional; we _likely_ can avoid doing the union trick and store just the type, or null
                if instance is None:
                    return None
                else:
                    return serialize(instance, inner_annotation[0])
                pass
            assert (
                type(instance) in inner_annotation
            ), f"{type(instance)} not in {inner_annotation}, {instance}"
            ma = [x for x in inner_annotation if type(instance) is x]
            assert len(ma) == 1
            ann_ = ma[0]
            return {"type": ann_.__name__, "data": serialize(instance, ann_)}
        elif (
            isinstance(instance, Base)
            and (instance.__class__.__name__ == getattr(annotation, "_name", None))
            or type(instance) == annotation
        ):
            data = {}
            for k, v in get_type_hints(type(instance)).items():
                try:
                    data[k] = serialize(getattr(instance, k), v)
                except Exception as e:
                    raise type(e)(f"Error serializing field {k!r}")
            assert (
                data
            ), f"Error serializing {instance=}, of type {type(instance)}, no data found. Did you type annotate?"
            return data

        else:
            assert (
                False
            ), f"Error serializing {instance!r}, of type {type(instance)!r} expected  {annotation}, got {type(instance)}"
    except Exception as e:
        raise type(e)(
            f"Error serialising {instance!r}, of type {type(instance)} expecting {annotation}, got {type(instance)}"
        ) from e


# type_ and annotation are _likely_ duplicate here as an annotation is likely a type, or  a List, Union, ....)
def deserialize(type_, annotation, data):
    assert type_ is annotation
    assert annotation != {}
    assert annotation is not dict
    if annotation is str:
        return data
    if annotation is type(None):
        return data
    if annotation is int:
        return data
    if annotation is bool:
        return data
    orig = getattr(annotation, "__origin__", None)
    if orig:
        if orig is tuple:
            assert isinstance(data, list)
            inner_annotation = annotation.__args__
            assert len(inner_annotation) == 1, inner_annotation
            return tuple(
                [deserialize(inner_annotation[0], inner_annotation[0], x) for x in data]
            )
        elif orig is list:
            assert isinstance(data, list)
            inner_annotation = annotation.__args__
            assert len(inner_annotation) == 1, inner_annotation
            return [
                deserialize(inner_annotation[0], inner_annotation[0], x) for x in data
            ]
        elif orig is Union:
            inner_annotation = annotation.__args__
            if len(inner_annotation) == 2 and inner_annotation[1] == type(None):
                assert inner_annotation[0] != None
                if data is None:
                    return None
                else:
                    return deserialize(inner_annotation[0], inner_annotation[0], data)
            real_type = [t for t in inner_annotation if t.__name__ == data["type"]]
            assert len(real_type) == 1, real_type
            real_type = real_type[0]
            return deserialize(real_type, real_type, data["data"])
        else:
            assert False
    elif issubclass(annotation, Base) or type(data) is dict:
        loc = {}
        new_ann = get_type_hints(annotation).items()
        assert new_ann
        for k, v in new_ann:
            assert k in data.keys(), f"{data}, {k}"
            if data[k] != 0:
                assert data[k] != {}, f"{data}, {k}"
            intermediate = deserialize(v, v, data[k])
            assert intermediate != {}, f"{v}, {data}, {k}"
            loc[k] = intermediate
        return annotation._deserialise(**loc)

    else:
        assert False, f"{annotation!r}, {data}"


class Node(Base):
    def __init__(self, value=None):
        self.value = value

    def __eq__(self, other):
        if not (type(self) == type(other)):
            return False

        tt = get_type_hints(type(self))
        for attr in tt:
            if not getattr(self, attr) == getattr(other, attr):
                return False

        return True


    @classmethod
    def _instance(cls):
        return cls()

    @classmethod
    def parse(cls, tokens):
        """
        Try to parse current `tokens` stream from current position. 

        Returns
        -------
        Tuple with the following items:
            - Node to insert at current position in the token tree; 
            - None if could not parse.

        """
        return cls(tokens[0]), tokens[1:]

    def is_whitespace(self):
        if not isinstance(self.value, str):
            return False
        return not bool(self.value.strip())

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.value}>"

    def to_json(self):
        return serialize(self, type(self))

    @classmethod
    def from_json(cls, data):
        return deserialize(cls, cls, data)


class Verbatim(Node):
    value: List[str]

    def __hash__(self):
        return hash(tuple(self.value))

    def __init__(self, value=None):
        self.value = value

    @classmethod
    def parse(cls, tokens):
        acc = []
        if len(tokens) < 5:
            return None
        if (tokens[0], tokens[1]) == ("`", "`") and tokens[2].strip():
            for i, t in enumerate(tokens[2:-2]):
                if t == "`" and tokens[i + 2] == "`":
                    return cls(acc), tokens[i + 4 :]
                else:
                    acc.append(t)
        return None

    @property
    def text(self):
        return "".join(self.value)

    def __len__(self):
        return sum(len(x) for x in self.value) + 4

    def __repr__(self):
        return RED("``" + "".join(self.value) + "``")

    def __hash__(self):
        return hash(tuple(self.value))


class Link(Node):
    """
    Links are usually the end goal of a directive,
    they are a way to link to another document.
    They contain a text; which will be what the user will see,
    as well as a reference to the document pointed to.
    They should also have an attribute to know whether the link is a
     - Local item (same document)
     - Internal item (same module)
     - External item (another module)
     - Web : a url to another page non papyri aware.
     - Exist: bool wether the thing they point to exists.


    - I'm wondering if those should be descendant of directive not to lose information and be able to reconsruct the
    directive from it.
    - A Link might get several token for multiline; I'm not sure about that either, and wether the inner text should be
      a block or not.
    """

    value: str
    reference: str
    kind: str
    exists: bool

    def __init__(self, value=None, reference=None, kind=None, exists=None):
        self.value = value
        self.reference = reference
        self.kind = kind
        self.exists = exists

    def __len__(self):
        return len(self.value)

    def __hash__(self):
        return hash((iself.value, self.reference, self.kind, self.exists))
class Directive(Node):

    value: List[str]
    domain: Union[str, None]
    role: Union[str, None]

    def __hash__(self):
        return hash((tuple(self.value), self.domain, self.role))

    def __init__(self, value, domain, role):
        self.value = value
        self.domain = domain
        if domain:
            assert role
        self.role = role

    @classmethod
    def _instance(cls):
        return cls("", "", "")

    @property
    def text(self):
        return "".join(self.value)

    @classmethod
    def parse(cls, tokens):
        acc = []
        consume_start = None
        domain, role = None, None
        if (
            (len(tokens) > 2)
            and tokens[0] == "`"
            and tokens[1] != "`"
            and tokens[1].strip()
        ):
            consume_start = 1
        elif (len(tokens) >= 4) and (tokens[0], tokens[2], tokens[3]) == (
            ":",
            ":",
            "`",
        ):
            domain, role = None, tokens[1]
            consume_start = 4
            pass
        elif len(tokens) >= 6 and (tokens[0], tokens[2], tokens[4], tokens[5]) == (
            ":",
            ":",
            ":",
            "`",
        ):
            domain, role = tokens[1], tokens[3]
            consume_start = 6

        if consume_start is None:
            return None

        for i, t in enumerate(tokens[consume_start:]):
            if t == "`":
                return cls(acc, domain, role), tokens[i + 1 + consume_start :]
            else:
                acc.append(t)

    def __len__(self):
        return sum(len(x) for x in self.value) + len(self.prefix)

    @property
    def prefix(self):
        prefix = ""
        if self.domain:
            prefix += ":" + self.domain
        if self.role:
            prefix += ":" + self.role + ":"
        return prefix

    def __repr__(self):
        prefix = ""
        if self.domain:
            prefix += ":" + self.domain
        if self.role:
            prefix += ":" + self.role + ":"
        # prefix = ''
        return GREEN(prefix) + HEADER("`" + "".join(self.value) + "`")


class Math(Node):
    value: List[str]

    @property
    def text(self):
        return "".join(self.value)

    def __hash__(self):
        return hash(tuple(self.value))


class Word(Node):
    value: str

    @classmethod
    def _instance(cls):
        return cls("")

    def __repr__(self):
        return UNDERLINE(self.value)

    def __len__(self):
        return len(self.value)

    def __hash__(self):
        return hash(self.value)


class Words(Node):
    """A sequence of words that does not start not ends with spaces"""

    value: str

    def __init__(self, value=None):
        self.value = value

    @classmethod
    def _instance(cls):
        return cls("")

    def __repr__(self):
        return UNDERLINE(self.value)

    def __len__(self):
        return len(self.value)

    def __hash__(self):
        return hash(self.value)


def lex(lines):
    acc = ""
    for i, l in enumerate(lines):
        assert isinstance(l, str), l
        for c in l:
            if c in " `*_:":
                if acc:
                    yield acc
                yield c
                acc = ""
            else:
                acc += c
        if acc:
            yield acc
            acc = ""
        if i != len(lines) - 1:
            yield " "


class FirstCombinator:
    def __init__(self, parsers):
        self.parsers = parsers

    def parse(self, tokens):
        for parser in self.parsers:
            res = parser.parse(tokens)
            if res is not None:
                return res

        return None


class Section(Node):
    children: List[
        Union[
            Code,
            Text,
            Fig,
            Paragraph,
            DefList,
            DefListItem,
            BlockDirective,
            Example,
            BlockVerbatim,
            Param,
        ]
    ]

    def __init__(self, children=None):
        if children is None:
            children = []
        self.children = children
        tt = get_type_hints(type(self))["children"].__args__[0].__args__
        for c in children:
            assert isinstance(c, tt), f"{c} not in {tt}"

    def __getitem__(self, k):
        return self.children[k]

    def __setitem__(self, k, v):
        self.children[k] = v

    def __iter__(self):
        return iter(self.children)

    def append(self, item):
        self.children.append(item)

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.children}>"

    def empty(self):
        return len(self.children) == 0

    def __bool__(self):
        return len(self.children) >= 0

    def __len__(self):
        return len(self.children)


class Param(Node):
    param: str
    type_: str
    desc: List[
        Union[
            Code,
            Text,
            Fig,
            Paragraph,
            DefListItem,
            DefList,
            BlockDirective,
            Example,
            BlockVerbatim,
            Math,
        ]
    ]

    def __init__(self, param=None, type_=None, desc=None):
        self.param = param
        self.type_ = type_
        self.desc = desc

    @property
    def children(self):
        return self.desc

    @children.setter
    def children(self, values):
        self.desc = values

    def __getitem__(self, index):
        return [self.param, self.type_, self.desc][index]

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: {self.param=}, {self.type_=}, {self.desc=}>"
        )

    def __hash__(self):
        return hash((self.param, self.type_, sefl.desc))

class Code(Node):
    entries: List[Tuple[Optional[str]]]
    out: str
    ce_status: str

    def __init__(self, entries=None, out=None, ce_status=None):
        self.entries = entries
        self.out = out
        self.ce_status = ce_status

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.entries=} {self.out=} {self.ce_status=}>"


class Text(Node):
    value: str


class Fig(Node):
    value: str


def compress_word(stream):
    i = len(stream)
    acc = []
    wds = ""
    assert isinstance(stream, list)
    for item in stream:
        if isinstance(item, Word):
            wds += item.value
        else:
            if wds:
                acc.append(Words(wds))
                wds = ""
            acc.append(item)
    if wds:
        acc.append(Words(wds))
    return acc


class Paragraph(Node):

    __slots__ = ["children", "width"]

    children: List[Union[Paragraph, Word, Words, Directive, Verbatim, Link, Math]]

    def __init__(self, children, width=80):
        self.children = children
        self.width = width

    def __hash__(self):
        return hash((tuple(self.children), self.width))

    def __eq__(self, other):
        return (type(self) == type(other)) and (self.children == other.children)

    @classmethod
    def _instance(cls):
        return cls([])

    @classmethod
    def parse_lines(cls, lines):
        assert isinstance(lines, list), lines
        assert lines
        tokens = list(lex(lines))

        rest = tokens
        acc = []
        parser = FirstCombinator([Directive, Verbatim, Word])
        while rest:
            parsed, rest = parser.parse(rest)
            acc.append(parsed)

        return cls(compress_word(acc))

    @property
    def references(self):
        refs = []
        for c in self.children:
            if isinstance(c, Directive) and c.role != "math":
                refs.append(c.text)
        return refs

    def __repr__(self):

        rw = self.rewrap(self.children, self.width)

        p = "\n".join(["".join(repr(x) for x in line) for line in rw])
        return f"""<Paragraph:\n{p}>"""

    @classmethod
    def rewrap(cls, tokens, max_len):
        acc = [[]]
        clen = 0
        for t in tokens:
            try:
                lent = len(t)
            except TypeError:
                lent = 0
            if clen + lent > max_len:
                # remove whitespace at EOL
                while acc and acc[-1][-1].is_whitespace():
                    acc[-1].pop()
                acc.append([])
                clen = 0

            # do no append whitespace at SOL
            if clen == 0 and t.is_whitespace():
                continue
            acc[-1].append(t)
            clen += lent
        # remove whitespace at EOF
        try:
            while acc and acc[-1][-1].is_whitespace():
                acc[-1].pop()
        except IndexError:
            pass
        return acc


def indent(text, marker="   |"):
    """
    Return the given text indented with 3 space plus a pipe for display.
    """
    lines = text.split("\n")
    return "\n".join(marker + l for l in lines)


def header_lines(lines):
    """
    Find lines indices for header
    """

    indices = []

    for i, l in enumerate(lines):
        if is_at_header(lines[i:]):
            indices.append(i)
    return indices


def separate(lines, indices):
    acc = []
    for i, j in zip([0] + indices, indices + [-1]):
        acc.append(lines[i:j])
    return acc


def with_indentation(lines, start_indent=0):
    """
    return pairs of indent_level and lines
    """

    indent = start_indent
    for l in lines:
        if (ls := l.lstrip()) :
            yield (indent := len(l) - len(ls)), l
        else:
            yield indent, l


def eat_while(lines, condition):
    acc = []
    for i, l in enumerate(lines):
        if condition(l):
            acc.append(l)
            continue
        break
    else:
        return acc, []
    return acc, lines[i:]


def make_blocks_2(lines):
    """
    WRONG:

    xxxxx

    yyyyyy

       zzzzz

    ttttttttt

    x and y should be 2blocks

    """
    if not lines:
        return []
    l0 = lines[0]

    ind0 = len(l0) - len(l0.lstrip())

    rest = lines
    acc = []
    while rest:
        blk, rest = eat_while(rest, lambda l: len(l) - len(l.lstrip()) == ind0)
        wht, rest = eat_while(rest, lambda l: not l.strip())
        ind, rest = eat_while(
            rest, lambda l: ((len(l) - len(l.lstrip())) > ind0 or not l.strip())
        )
        acc.append(Block(blk, wht, ind))

    return acc


def make_block_3(lines: "Lines"):
    """
    I think the correct alternative is that each block may get an indented children, and that a block is thus:

    - a) The sequence of consecutive non blank lines with 0 indentation
    - b) The (potentially absent) blank lines leading to the indent block
    - c) The Raw indent block (we can decide to recurse, or not later)
    - d?) The trailing blank line at the end of the block leading to the next one. I think the blank line will be in the
      raw indent block

    """
    assert isinstance(lines, Lines)
    a: List[Lines]
    b: List[Lines]
    c: List[Lines]
    (a, b, c) = [], [], []
    blocks = []
    state = "a"

    for l in lines:
        if l.indent == 0:
            if state == "a":
                a.append(l)
            elif state in ("b", "c"):
                blocks.append((a, b, c))
                a, b, c = [l], [], []
                state = "a"
            else:
                raise ValueError
        elif l.indent is None:
            if state == "a":
                state = "b"
                b.append(l)
            elif state == "b":
                b.append(l)
            elif state == "c":
                c.append(l)
            else:
                raise ValueError
        elif l.indent > 0:
            if state in ("a", "b"):
                state = "c"
                c.append(l)
            elif state == "c":
                c.append(l)
            else:
                raise ValueError

    blocks.append((a, b, c))
    return blocks


class Block(Node):
    """
    The following is wrong for some case, in particular if there are many paragraph in a row with 0 indent.
    we can't ignore blank lines.

    ---

    A chunk of lines that breaks when the indentation reaches
    - the last of a list of blank lines if indentation is consistant
    - the last non-0  indented lines


    Note we likely want the _body_ lines and then the _indented_ lines if any, which would mean we
    cut after the first blank lines and expect indents, otherwise there is not indent.
    and likely if there is a blank lnes as  a property.

    ----

    I think the correct alternative is that each block may get an indented children, and that a block is thus:

    - 1) The sequence of consecutive non blank lines with 0 indentation
    - 2) The (potentially absent) blank lines leading to the indent block
    - 3) The Raw indent block (we can decide to recurse, or not later)
    - 4) The trailing blank line at the end of the block leading to the next one.

    """

    COLOR = lambda x: x

    def __init__(self, lines, wh, ind, *, reason=None):
        if not lines:
            lines = [
                ":: workaround numpyoc summary/ext summary bug in take2::Line.__init__"
            ]
        self.lines = Lines(lines)
        self.wh = Lines(wh)
        self.ind = Lines(ind)
        self.reason = reason

    def __repr__(self):
        return type(self).COLOR(
            f"<{self.__class__.__name__} '{len(self.lines)},{len(self.wh)},{len(self.ind)}'> with\n"
            + indent("\n".join([str(l) for l in self.lines]), "    ")
            + "\n"
            + indent("\n".join([str(w) for w in self.wh]), "    ")
            + "\n"
            + indent("\n".join([repr(x) for x in self.ind]), "    ")
        )


class BlockError(Block):
    @classmethod
    def from_block(cls, block):
        return cls(block.lines, block.wh, block.ind)


# class Section:
#    """
#    A section start (or not) with a header.
#
#    And have a body
#    """
#
#    def __init__(self, lines):
#        self.lines = lines
#
#    @property
#    def header(self):
#        if is_at_header(self.lines):
#            return self.lines[0:2]
#        else:
#            return None, None
#
#    @property
#    def body(self):
#        if is_at_header(self.lines):
#            return make_blocks_2(self.lines[2:])
#        else:
#            return make_blocks_2(self.lines)
#
#    def __repr__(self):
#        return (
#            f"<Section header='{self.header[0]}' body-len='{len(self.lines)}'> with\n"
#            + indent("\n".join([str(b) for b in self.body]) + "...END\n\n", "    |")
#        )


# wrapper around handling lines


class Line(Node):

    _line: str
    _number: int
    _offset: int

    def __init__(self, line, number, offset=0):
        assert isinstance(line, str)
        assert "\n" not in line, line
        self._line = line
        self._number = number
        self._offset = offset

    def __eq__(self, other):
        for attr in ["_line", "_number", "_offset"]:
            if getattr(self, attr) != getattr(other, attr):
                return False

        return type(self) == type(other)

    @classmethod
    def _instance(cls):
        return cls("", 0)

    @property
    def text(self):
        return self._line.rstrip()[self._offset :]

    @property
    def blank(self):
        return self._line.strip() == ""

    def __getattr__(self, missing):
        return getattr(self._line, missing)

    def __repr__(self):
        return f"<Line {self._number: 3d} {str(self.indent):>4}| {self._line[self._offset:]}>"

    @property
    def indent(self):
        if self.blank:
            return None
        return len(self._line) - len(self._line.lstrip()) - self._offset


class Lines(Node):

    _lines: List[Line]

    def __init__(self, lines=None):
        if lines is None:
            lines = []
        assert isinstance(lines, (list, Lines))
        for l in lines:
            assert isinstance(l, (str, Line)), f"got {l}"
            if isinstance(l, str):
                assert "\n" not in l
            if isinstance(l, Line):
                assert "\n" not in l._line

        self._lines = [
            l if isinstance(l, Line) else Line(l, n) for n, l in enumerate(lines)
        ]

    def __eq__(self, other):
        return (type(self) == type(other)) and (self._lines == other._lines)

    @classmethod
    def _instance(cls):
        return cls([])

    def __iter__(self):
        return iter(self._lines)

    def __getitem__(self, sl):
        if isinstance(sl, int):
            return self._lines[sl]
        else:
            return Lines(self._lines[sl])

    def __repr__(self):
        rep = f"<Lines {len(self._lines)} lines:"
        for l in self._lines:
            rep += f"\n    {l}"
        rep += ">"
        return rep

    def dedented(self):
        d = min([l.indent for l in self._lines if l.indent is not None])

        new_lines = []
        for l in self._lines:
            nl = Line(l._line, l._number, l._offset + d)
            new_lines.append(nl)
        return Lines(new_lines)

    def __len__(self):
        return len(self._lines)

    def __add__(self, other):
        if not isinstance(other, Lines):
            return NotImplemented
        return Lines(self._lines + other._lines)


class Document:
    def __init__(self, lines):
        self.lines = lines

    @property
    def sections(self):
        indices = header_lines(self.lines)
        return [Section(l) for l in separate(self.lines, indices)]

    def __repr__(self):
        acc = ""
        for i, s in enumerate(self.sections[0:]):
            acc += "\n" + repr(s)
        return "<Document > with" + indent(acc)


# d = Document(lines[:])
# for i, l in with_indentation(repr(d).split("\n")):
#    print(i, l)


def is_at_header(lines) -> bool:
    """
    Given a list of lines (str), return wether or not we are (likely) at a header

    A header is (generally) of the form:
        - One line with text
        - one line some lenght with one of -_=*~ (and space on each side).

    In practice user do not use the same length, and some things may trigger
    false positive ( tracebacks in docstrings print with a long line of dashes
    (-).

    We could also peek at the line n-1, and make sure it is a blankline, also
    some libraries (scipy), use 0 level header with both over and underline
    (this is not implemented)

    We might also be able to find that headers are actually blocs as well, and
    blockify a full document, though we have to be careful, some thing so not
    have spaces after headers. (numpy.__doc__)
    """
    if len(lines) < 2:
        return False
    l0, l1, *rest = lines
    if len(l0.strip()) != len(l1.strip()):
        return False
    if len(s := set(l1.strip())) != 1:
        return False
    if next(iter(s)) in "-=":
        return True
    return False


class Header:
    """
    a header node
    """

    def __init__(self, lines):
        assert len(lines) >= 2, f"{lines=}"
        self._lines = lines
        self.level = None

    def __repr__(self):
        return (
            f"<Header {self.level}> with\n"
            + RED(indent(str(self._lines[0]), "    "))
            + "\n"
            + RED(indent(str(self._lines[1]), "    "))
            + "\n"
            + RED(indent("\n".join(str(x) for x in self._lines[2:]), "    "))
        )


class BlockDirective(Block):
    lines: Lines
    wh: Lines
    ind: Lines

    directive_name: str
    args0: List[str]
    inner: Optional[Paragraph]
    COLOR = ORANGE

    @property
    def children(self):
        if self.inner is not None:
            return [self.inner]
        else:
            return []

    @children.setter
    def children(self, value):
        assert len(value) in [0, 1]
        if len(value) == 0:
            assert not self.inner
        else:
            self.inner = value[0]

    def __init__(self, lines=None, wh=None, ind=None):
        if None in (lines, wh, ind):
            return
        self.lines = lines
        self.wh = wh
        self.ind = ind

        # numpy doc bug
        l = lines[0]._line
        if l.startswith("..version"):
            lines[0]._line = ".. " + l[2:]
        # end numpy doc bug
        assert lines[0].startswith(".. ")
        l0 = lines[0]
        pred, *postd = l0.split("::")
        assert pred.startswith(".. ")
        self.directive_name = pred[3:]
        self.args0 = postd
        if self.ind:
            self.inner = Paragraph.parse_lines([x._line for x in self.ind])
        else:
            self.inner = None


class BlockVerbatim(Block):

    lines: Lines

    def __init__(self, lines):

        self.lines = lines

    def __eq__(self, other):
        return (type(self) == type(other)) and (self.lines == other.lines)

    @classmethod
    def _instance(cls):
        return cls("")

    def __repr__(self):
        return type(self).COLOR(
            f"<{self.__class__.__name__} '{len(self.lines)}'> with\n"
            + indent("\n".join([str(l) for l in self.lines]), "    ")
        )

    def to_json(self):
        return serialize(self, type(self))


class DefList(Block):
    children: List[DefListItem]

    def __init__(self, children=None):
        self.children = children

    def __repr__(self):
        return type(self).COLOR(
            f"<{self.__class__.__name__} '{len(self.children)}'> with\n"
            + indent("\n".join([str(l) for l in self.children]), "    ")
        )


class DefListItem(Block):
    lines: Lines
    wh: Lines
    ind: Lines
    dt: Paragraph  # TODO: this is technically incorrect and should be a single term, (word, directive or link is my guess).
    dd: Paragraph

    @property
    def children(self):
        return [self.dt, self.dd]

    @children.setter
    def children(self, value):
        self.dt, self.dd = value

    def __init__(self, lines=None, wh=None, ind=None, dl=None, dd=None):
        self.lines = lines
        self.wh = wh
        self.ind = ind
        self.dt = dl
        self.dd = dd

    @classmethod
    def parse(cls, lines, wh, ind):
        dl = Paragraph.parse_lines([l.text.strip() for l in lines])
        assert len(dl.children) == 1
        dd = Paragraph.parse_lines([x._line for x in ind.dedented()])
        return cls(lines, wh, ind, dl, dd)

    COLOR = BLUE


from dataclasses import dataclass


class Ref(Node):
    name: str
    ref: Optional[str]
    exists: Optional[bool]

    def __init__(self, name=None, ref=None, exists=None):
        self.name = name
        self.ref = ref
        self.exists = exists

    def __hash__(self):
        return hash((self.name, self.ref, self.exists))

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} {self.ref} {self.exists}>"


class SeeAlsoItem(Node):
    name: Ref
    descriptions: List[Paragraph]
    # there are a few case when the lhs is `:func:something`... in scipy.
    type: Optional[str]

    def __init__(self, name=None, descriptions=None, type_=None):
        self.name = name
        if descriptions is not None:
            for d in descriptions:
                assert isinstance(d, Paragraph), repr(d)
        self.descriptions= descriptions
        self.type = type_

    # @classmethod
    # def from_json(cls, name, descriptions, type):
    #    assert isinstance(descriptions, list)
    #    return cls(Ref(**name), descriptions, type)
    #    assert isinstance(self.descriptions, list)

    def __hash__(self):
        return hash((self.name, tuple(self.descriptions)))

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}: {self.name} {self.type} {self.descriptions}>"
        )


class Example(Block):
    lines: Lines
    wh: Lines
    ind: Lines

    def __init__(self, lines=None, wh=None, ind=None):
        self.lines = lines
        self.wh = wh
        self.ind = ind

    COLOR = GREEN


def header_pass(block):
    """
    Check each block for potential header, if found, split (or extract) the given block into a header.

    Parameters
    ----------
    block : Block
        A block to split or extract

    Returns
    -------
    list
        A list of blocks and/or header

    """
    # TODO: Add logic to handle doctests raising exceptions.

    if len(block.lines) == 2 and is_at_header(block.lines):
        assert not block.ind
        return [Header(block.lines + block.wh)]
    elif len(block.lines) >= 2 and is_at_header(block.lines):
        h = Header(block.lines[:2])
        block.lines = block.lines[2:]
        return (h, block)
    return (block,)


def header_level_pass(blocks):
    """
    Iter over all top level nodes, updating the header level.

    For each encountered header, collect the type of marker use to underline,
    and increase the counter on newly encountered marker.

    Update the level attribute of the header with the corresponding value.

    Parameters
    ----------
    blocks : Block
        A block to split or extract

    """
    seen = {}
    for b in blocks:
        if not isinstance(b, Header):
            continue
        marker_set = set(b._lines[1].strip())
        assert len(marker_set) == 1, b
        marker = next(iter(marker_set))
        if marker not in seen:
            seen[marker] = len(seen)
        b.level = seen[marker]

    return blocks


def example_pass(block):
    if not type(block) == Block:
        return [block]
    if block.lines and block.lines[0].startswith(">>>"):
        return [Example(block.lines, block.wh, block.ind)]
    return [block]


def deflist_pass(blocks):
    acc = []
    deflist = []
    for block in blocks:
        if len(block.lines) == 1:
            p = Paragraph.parse_lines([l.text.strip() for l in block.lines])
        if (
            len(block.lines) == 1
            and (not block.wh)
            and block.ind
            and len(p.children) == 1
        ):
            deflist.append(
                DefListItem.parse(block.lines.dedented(), block.wh, block.ind)
            )
        else:
            if deflist:
                acc.append(DefList(deflist))
                deflist = []
            acc.append(block)
    if deflist:
        acc.append(DefList(deflist))
    return acc


def deflist_item_pass(block):
    assert False
    if not type(block) == Block:
        return [block]
    if len(block.lines) == 1 and (not block.wh) and block.ind:
        return [DefListItem(block.lines, block.wh, block.ind)]
    return [block]


def block_directive_pass(block):
    if not type(block) == Block:
        return [block]
    if len(block.lines) >= 1 and (block.lines[0].startswith("..")):
        return [BlockDirective(block.lines, block.wh, block.ind)]
    return [block]


def paragraphs_pass(block):
    if not type(block) == Block:
        return [block]
    else:
        # likely incorrect for the indented part.
        if block.ind:
            assert isinstance(block.lines, Lines)
            lines = block.lines
            if not lines:
                return [BlockError.from_block(block)]
            if lines[-1]._line.endswith("::"):
                return [Paragraph.parse_lines([l._line for l in block.lines])] + [
                    BlockVerbatim(block.ind.dedented())
                ]
            else:
                sub = [Block(*b) for b in make_block_3(block.ind.dedented())]
                sub = deflist_pass(sub)
                sub = [x for pairs in sub for x in paragraphs_pass(pairs)]
                return [Paragraph.parse_lines([l._line for l in block.lines])] + sub
        else:
            return [Paragraph.parse_lines([l._line for l in block.lines])]


def empty_pass(doc):
    ret = []
    for b in doc:
        if not block.lines:
            assert not block.wh
            assert not block.ind
            continue
        ret.append(b)
    return ret


def get_object(qual):
    parts = qual.split(".")

    for i in range(len(parts), 1, -1):
        mod_p, _ = parts[:i], parts[i:]
        mod_n = ".".join(mod_p)
        try:
            __import__(mod_n)
            break
        except Exception:
            continue

    obj = __import__(parts[0])
    for p in parts[1:]:
        obj = getattr(obj, p)
    return obj


def assert_block_lines(blocks):
    for b in blocks:
        assert b.lines

def main(text):

    doc = [Block(*b) for b in make_block_3(Lines(text.split("\n"))[:])]
    assert_block_lines(doc), "raw blocks"
    doc = [x for pairs in doc for x in header_pass(pairs)]
    doc = header_level_pass(doc)
    doc = [x for pairs in doc for x in example_pass(pairs)]
    doc = [x for pairs in doc for x in block_directive_pass(pairs)]
    doc = deflist_pass(doc)
    doc = [x for pairs in doc for x in paragraphs_pass(pairs)]

    # TODO: third pass to set the header level for each header.
    # TODO: forth pass to make sections.

    #    print(b)
    # print(ex)
    # for w in [80, 120]:
    #    p = Paragraph.parse_lines(ex.split("\n"))
    #    p.width = w
    #    print(p)
    #    print()
    return doc


if __name__ == "__main__":
    if len(sys.argv) > 1:
        what = sys.argv[1]
    else:
        what = "numpy"
    ex = get_object(what).__doc__
    ex = dedent_but_first(ex)
    doc = main(ex)
    for b in doc:
        print(b)
