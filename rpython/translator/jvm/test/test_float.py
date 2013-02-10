import py
from rpython.translator.jvm.test.runtest import JvmTest
from rpython.rtyper.test.test_rfloat import BaseTestRfloat

# ====> ../../../rpython/test/test_rfloat.py

class TestJvmFloat(JvmTest, BaseTestRfloat):

    def test_parse_float(self):
        ex = ['', '    ', '0', '1', '-1.5', '1.5E2', '2.5e-1', ' 0 ', '?']
        def fn(i):
            s = ex[i]
            try:
                return float(s)
            except ValueError:
                return -999.0
        
        for i in range(len(ex)):
            expected = fn(i)
            res = self.interpret(fn, [i])
            assert res == expected

    def test_r_singlefloat(self):
        py.test.skip("not implemented: single-precision floats")

    def test_format_float(self):
        from rpython.rlib.rfloat import _formatd
        def fn(precision):
            return _formatd(10.01, 'd', precision, 0)

        res = self.interpret(fn, [2])
        assert res == "10.01"

        res = self.interpret(fn, [1])
        assert res == "10.0"

    def test_formatd(self):
        py.test.skip('formatd is broken on ootype')

    def test_formatd_repr(self):
        py.test.skip('formatd is broken on ootype')

    def test_formatd_huge(self):
        py.test.skip('formatd is broken on ootype')

    def test_parts_to_float(self):
        py.test.skip('parts_to_float is broken on ootype')
