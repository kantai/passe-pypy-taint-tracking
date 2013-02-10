""" String builder interface and string functions
"""

from rpython.annotator.model import (SomeObject, SomeString, s_None, SomeChar,
    SomeInteger, SomeUnicodeCodePoint, SomeUnicodeString, SomePtr, SomePBC)
from rpython.rlib.rarithmetic import ovfcheck
from rpython.tool.pairtype import pair, pairtype
from rpython.rtyper.extregistry import ExtRegistryEntry


# -------------- public API for string functions -----------------------
def split(value, by, maxsplit=-1):
    bylen = len(by)
    if bylen == 0:
        raise ValueError("empty separator")

    res = []
    start = 0
    while maxsplit != 0:
        next = value.find(by, start)
        if next < 0:
            break
        res.append(value[start:next])
        start = next + bylen
        maxsplit -= 1   # NB. if it's already < 0, it stays < 0

    res.append(value[start:len(value)])
    return res

def rsplit(value, by, maxsplit=-1):
    res = []
    end = len(value)
    bylen = len(by)
    if bylen == 0:
        raise ValueError("empty separator")

    while maxsplit != 0:
        next = value.rfind(by, 0, end)
        if next < 0:
            break
        res.append(value[next+bylen:end])
        end = next
        maxsplit -= 1   # NB. if it's already < 0, it stays < 0

    res.append(value[:end])
    res.reverse()
    return res

# -------------- public API ---------------------------------

INIT_SIZE = 100 # XXX tweak

class AbstractStringBuilder(object):
    def __init__(self, init_size=INIT_SIZE):
        self.l = []
        self.size = 0

    def _grow(self, size):
        try:
            self.size = ovfcheck(self.size + size)
        except OverflowError:
            raise MemoryError

    def append(self, s):
        assert isinstance(s, self.tp)
        self.l.append(s)
        self._grow(len(s))

    def append_slice(self, s, start, end):
        assert isinstance(s, self.tp)
        assert 0 <= start <= end <= len(s)
        s = s[start:end]
        self.l.append(s)
        self._grow(len(s))

    def append_multiple_char(self, c, times):
        assert isinstance(c, self.tp)
        self.l.append(c * times)
        self._grow(times)

    def append_charpsize(self, s, size):
        l = []
        for i in xrange(size):
            l.append(s[i])
        self.l.append(self.tp("").join(l))
        self._grow(size)

    def build(self):
        return self.tp("").join(self.l)

    def getlength(self):
        return len(self.build())

class StringBuilder(AbstractStringBuilder):
    tp = str

class UnicodeBuilder(AbstractStringBuilder):
    tp = unicode


# ------------------------------------------------------------
# ----------------- implementation details -------------------
# ------------------------------------------------------------

class SomeStringBuilder(SomeObject):
    def method_append(self, s_str):
        if s_str != s_None:
            assert isinstance(s_str, (SomeString, SomeChar))
        return s_None

    def method_append_slice(self, s_str, s_start, s_end):
        if s_str != s_None:
            assert isinstance(s_str, SomeString)
        assert isinstance(s_start, SomeInteger)
        assert isinstance(s_end, SomeInteger)
        return s_None

    def method_append_multiple_char(self, s_char, s_times):
        assert isinstance(s_char, SomeChar)
        assert isinstance(s_times, SomeInteger)
        return s_None

    def method_append_charpsize(self, s_ptr, s_size):
        assert isinstance(s_ptr, SomePtr)
        assert isinstance(s_size, SomeInteger)
        return s_None

    def method_getlength(self):
        return SomeInteger(nonneg=True)

    def method_build(self):
        return SomeString()

    def rtyper_makerepr(self, rtyper):
        return rtyper.type_system.rbuilder.stringbuilder_repr

    def rtyper_makekey(self):
        return self.__class__,


class SomeUnicodeBuilder(SomeObject):
    def method_append(self, s_str):
        if s_str != s_None:
            assert isinstance(s_str, (SomeUnicodeCodePoint, SomeUnicodeString))
        return s_None

    def method_append_slice(self, s_str, s_start, s_end):
        if s_str != s_None:
            assert isinstance(s_str, SomeUnicodeString)
        assert isinstance(s_start, SomeInteger)
        assert isinstance(s_end, SomeInteger)
        return s_None

    def method_append_multiple_char(self, s_char, s_times):
        assert isinstance(s_char, SomeUnicodeCodePoint)
        assert isinstance(s_times, SomeInteger)
        return s_None

    def method_append_charpsize(self, s_ptr, s_size):
        assert isinstance(s_ptr, SomePtr)
        assert isinstance(s_size, SomeInteger)
        return s_None

    def method_getlength(self):
        return SomeInteger(nonneg=True)

    def method_build(self):
        return SomeUnicodeString()

    def rtyper_makerepr(self, rtyper):
        return rtyper.type_system.rbuilder.unicodebuilder_repr

    def rtyper_makekey(self):
        return self.__class__,


class BaseEntry(object):
    def compute_result_annotation(self, s_init_size=None):
        if s_init_size is not None:
            assert isinstance(s_init_size, SomeInteger)
        if self.use_unicode:
            return SomeUnicodeBuilder()
        return SomeStringBuilder()

    def specialize_call(self, hop):
        return hop.r_result.rtyper_new(hop)


class StringBuilderEntry(BaseEntry, ExtRegistryEntry):
    _about_ = StringBuilder
    use_unicode = False


class UnicodeBuilderEntry(BaseEntry, ExtRegistryEntry):
    _about_ = UnicodeBuilder
    use_unicode = True


class __extend__(pairtype(SomeStringBuilder, SomePBC)):
    def union((sb, p)):
        assert p.const is None
        return SomeStringBuilder()


class __extend__(pairtype(SomePBC, SomeStringBuilder)):
    def union((p, sb)):
        assert p.const is None
        return SomeStringBuilder()


class __extend__(pairtype(SomeUnicodeBuilder, SomePBC)):
    def union((sb, p)):
        assert p.const is None
        return SomeUnicodeBuilder()


class __extend__(pairtype(SomePBC, SomeUnicodeBuilder)):
    def union((p, sb)):
        assert p.const is None
        return SomeUnicodeBuilder()

#___________________________________________________________________
# Support functions for SomeString.no_nul

def assert_str0(fname):
    assert '\x00' not in fname, "NUL byte in string"
    return fname

class Entry(ExtRegistryEntry):
    _about_ = assert_str0

    def compute_result_annotation(self, s_obj):
        if s_None.contains(s_obj):
            return s_obj
        assert isinstance(s_obj, (SomeString, SomeUnicodeString))
        if s_obj.no_nul:
            return s_obj
        new_s_obj = SomeObject.__new__(s_obj.__class__)
        new_s_obj.__dict__ = s_obj.__dict__.copy()
        new_s_obj.no_nul = True
        return new_s_obj

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        return hop.inputarg(hop.args_r[0], arg=0)

def check_str0(fname):
    """A 'probe' to trigger a failure at translation time, if the
    string was not proved to not contain NUL characters."""
    assert '\x00' not in fname, "NUL byte in string"

class Entry(ExtRegistryEntry):
    _about_ = check_str0

    def compute_result_annotation(self, s_obj):
        if not isinstance(s_obj, (SomeString, SomeUnicodeString)):
            return s_obj
        if not s_obj.no_nul:
            raise ValueError("Value is not no_nul")

    def specialize_call(self, hop):
        hop.exception_cannot_occur()

