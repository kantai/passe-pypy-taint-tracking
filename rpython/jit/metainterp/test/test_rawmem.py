from rpython.jit.metainterp.test.support import LLJitMixin
from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rawstorage import (alloc_raw_storage, raw_storage_setitem,
                                  free_raw_storage, raw_storage_getitem)

class RawMemTests(object):
    def test_cast_void_ptr(self):
        TP = lltype.Array(lltype.Float, hints={"nolength": True})
        VOID_TP = lltype.Array(lltype.Void, hints={"nolength": True, "uncast_on_llgraph": True})
        class A(object):
            def __init__(self, x):
                self.storage = rffi.cast(lltype.Ptr(VOID_TP), x)

        def f(n):
            x = lltype.malloc(TP, n, flavor="raw", zero=True)
            a = A(x)
            s = 0.0
            rffi.cast(lltype.Ptr(TP), a.storage)[0] = 1.0
            s += rffi.cast(lltype.Ptr(TP), a.storage)[0]
            lltype.free(x, flavor="raw")
            return s
        self.interp_operations(f, [10])

    def test_fixed_size_malloc(self):
        TIMEVAL = lltype.Struct('dummy', ('tv_sec', rffi.LONG), ('tv_usec', rffi.LONG))
        def f():
            p = lltype.malloc(TIMEVAL, flavor='raw')
            lltype.free(p, flavor='raw')
            return 42
        res = self.interp_operations(f, [])
        assert res == 42
        self.check_operations_history({'call': 2, 'guard_no_exception': 1,
                                       'finish': 1})

    def test_raw_storage_int(self):
        def f():
            p = alloc_raw_storage(15)
            raw_storage_setitem(p, 3, 24)
            res = raw_storage_getitem(lltype.Signed, p, 3)
            free_raw_storage(p)
            return res
        res = self.interp_operations(f, [])
        assert res == 24
        self.check_operations_history({'call': 2, 'guard_no_exception': 1,
                                       'raw_store': 1, 'raw_load': 1,
                                       'finish': 1})

    def test_raw_storage_float(self):
        def f():
            p = alloc_raw_storage(15)
            raw_storage_setitem(p, 3, 2.4e15)
            res = raw_storage_getitem(lltype.Float, p, 3)
            free_raw_storage(p)
            return res
        res = self.interp_operations(f, [])
        assert res == 2.4e15
        self.check_operations_history({'call': 2, 'guard_no_exception': 1,
                                       'raw_store': 1, 'raw_load': 1,
                                       'finish': 1})

class TestRawMem(RawMemTests, LLJitMixin):
    pass
