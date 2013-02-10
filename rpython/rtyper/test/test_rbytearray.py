
from rpython.rtyper.test.tool import BaseRtypingTest, LLRtypeMixin
from rpython.rtyper.lltypesystem.rbytearray import hlbytearray
from rpython.rtyper.annlowlevel import llstr, hlstr

class TestByteArray(BaseRtypingTest, LLRtypeMixin):
    def test_bytearray_creation(self):
        def f(x):
            if x:
                b = bytearray(str(x))
            else:
                b = bytearray("def")
            return b
        ll_res = self.interpret(f, [0])
        assert hlbytearray(ll_res) == "def"
        ll_res = self.interpret(f, [1])
        assert hlbytearray(ll_res) == "1"

    def test_addition(self):
        def f(x):
            return bytearray("a") + hlstr(x)

        ll_res = self.interpret(f, [llstr("def")])
        assert hlbytearray(ll_res) == "adef"

        def f2(x):
            return hlstr(x) + bytearray("a")

        ll_res = self.interpret(f2, [llstr("def")])
        assert hlbytearray(ll_res) == "defa"

        def f3(x):
            return bytearray(hlstr(x)) + bytearray("a")

        ll_res = self.interpret(f3, [llstr("def")])
        assert hlbytearray(ll_res) == "defa"

    def test_getitem_setitem(self):
        def f(s, i, c):
            b = bytearray(hlstr(s))
            b[i] = c
            return b[i] + b[i + 1] * 255

        ll_res = self.interpret(f, [llstr("abc"), 1, ord('d')])
        assert ll_res == ord('d') + ord('c') * 255
