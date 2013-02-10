import py
from rpython.translator.cli.test.runtest import CliTest
from rpython.rtyper.test.test_rint import TestOOtype as _TestOOtype # so py.test won't run the base test

class TestCliInt(CliTest, _TestOOtype):
    def test_char_constant(self):
        def dummyfn(i):
            return chr(i)
        res = self.interpret(dummyfn, [ord(' ')])
        assert res == ' '
        # remove the following test, it's not supported by CLI
##        res = self.interpret(dummyfn, [0])
##        assert res == '\0'
        res = self.interpret(dummyfn, [ord('a')])
        assert res == 'a'

    def test_rarithmetic(self):
        pass # it doesn't make sense here

    div_mod_iteration_count = 20
