
from rpython.jit.metainterp.test.test_recursive import RecursiveTests
from rpython.jit.backend.x86.test.test_basic import Jit386Mixin

class TestRecursive(Jit386Mixin, RecursiveTests):
    # for the individual tests see
    # ====> ../../../metainterp/test/test_recursive.py
    pass
