import py
from rpython.jit.backend.cli.test.test_zrpy_basic import CliTranslatedJitMixin
from rpython.jit.metainterp.test import test_virtualizable


class TestVirtualizable(CliTranslatedJitMixin, test_virtualizable.TestOOtype):
    # for the individual tests see
    # ====> ../../../metainterp/test/test_virtualizable.py

    pass
