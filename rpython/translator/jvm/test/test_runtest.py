from rpython.translator.oosupport.test_template.runtest import BaseTestRunTest
from rpython.translator.jvm.test.runtest import JvmTest

class TestRunTest(BaseTestRunTest, JvmTest):
    def test_big_ullong(self):
        import py
        py.test.skip('fixme!')
