
import py, sys
from pypy.module.pypyjit.test_pypy_c.test_00_model import BaseTestPyPyC


class TestDicts(BaseTestPyPyC):
    def test_strdict(self):
        def fn(n):
            import sys
            d = {}
            class A(object):
                pass
            a = A()
            a.x = 1
            for s in sys.modules.keys() * 1000:
                inc = a.x # ID: look
                d[s] = d.get(s, 0) + inc
            return sum(d.values())
        #
        log = self.run(fn, [1000])
        assert log.result % 1000 == 0
        loop, = log.loops_by_filename(self.filepath)
        ops = loop.ops_by_id('look')
        assert log.opnames(ops) == ['setfield_gc',
                                    'guard_not_invalidated']

    def test_identitydict(self):
        def fn(n):
            class X(object):
                pass
            x = X()
            d = {}
            d[x] = 1
            res = 0
            for i in range(300):
                value = d[x]  # ID: getitem
                res += value
            return res
        #
        log = self.run(fn, [1000])
        assert log.result == 300
        loop, = log.loops_by_filename(self.filepath)
        # check that the call to ll_dict_lookup is not a call_may_force, the
        # gc_id call is hoisted out of the loop, the id of a value obviously
        # can't change ;)
        assert loop.match_by_id("getitem", """
            i26 = call(ConstClass(ll_dict_lookup), p18, p6, i25, descr=...)
            ...
            p33 = getinteriorfield_gc(p31, i26, descr=<InteriorFieldDescr <FieldP dictentry.value .*>>)
            ...
        """)

    def test_list(self):
        def main(n):
            i = 0
            while i < n:
                z = list(())
                z.append(1)
                i += z[-1] / len(z)
            return i

        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        assert loop.match("""
            i7 = int_lt(i5, i6)
            guard_true(i7, descr=...)
            guard_not_invalidated(descr=...)
            i9 = int_add(i5, 1)
            --TICK--
            jump(..., descr=...)
        """)

    def test_non_virtual_dict(self):
        def main(n):
            i = 0
            while i < n:
                d = {str(i): i}
                i += d[str(i)] - i + 1
            return i

        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        assert loop.match("""
            i8 = int_lt(i5, i7)
            guard_true(i8, descr=...)
            guard_not_invalidated(descr=...)
            p10 = call(ConstClass(ll_int_str), i5, descr=<Callr . i EF=3>)
            guard_no_exception(descr=...)
            i12 = call(ConstClass(ll_strhash), p10, descr=<Calli . r EF=0>)
            p13 = new(descr=...)
            p15 = new_array(8, descr=<ArrayX .*>)
            setfield_gc(p13, p15, descr=<FieldP dicttable.entries .*>)
            i17 = call(ConstClass(ll_dict_lookup_trampoline), p13, p10, i12, descr=<Calli . rri EF=4>)
            setfield_gc(p13, 16, descr=<FieldS dicttable.resize_counter .*>)
            guard_no_exception(descr=...)
            p20 = new_with_vtable(ConstClass(W_IntObject))
            call(ConstClass(_ll_dict_setitem_lookup_done_trampoline), p13, p10, p20, i12, i17, descr=<Callv 0 rrrii EF=4>)
            setfield_gc(p20, i5, descr=<FieldS .*W_IntObject.inst_intval .*>)
            guard_no_exception(descr=...)
            i23 = call(ConstClass(ll_dict_lookup_trampoline), p13, p10, i12, descr=<Calli . rri EF=4>)
            guard_no_exception(descr=...)
            i26 = int_and(i23, .*)
            i27 = int_is_true(i26)
            guard_false(i27, descr=...)
            p28 = getfield_gc(p13, descr=<FieldP dicttable.entries .*>)
            p29 = getinteriorfield_gc(p28, i23, descr=<InteriorFieldDescr <FieldP dictentry.value .*>>)
            guard_nonnull_class(p29, ConstClass(W_IntObject), descr=...)
            i31 = getfield_gc_pure(p29, descr=<FieldS .*W_IntObject.inst_intval .*>)
            i32 = int_sub_ovf(i31, i5)
            guard_no_overflow(descr=...)
            i34 = int_add_ovf(i32, 1)
            guard_no_overflow(descr=...)
            i35 = int_add_ovf(i5, i34)
            guard_no_overflow(descr=...)
            --TICK--
            jump(p0, p1, p2, p3, p4, i35, p13, i7, descr=...)
        """)

    def test_floatlist_unpack_without_calls(self):
        def fn(n):
            l = [2.3, 3.4, 4.5]
            for i in range(n):
                x, y, z = l # ID: look
        #
        log = self.run(fn, [1000])
        loop, = log.loops_by_filename(self.filepath)
        ops = loop.ops_by_id('look')
        assert 'call' not in log.opnames(ops)

    #XXX the following tests only work with strategies enabled

    def test_should_not_create_intobject_with_sets(self):
        def main(n):
            i = 0
            s = set()
            while i < n:
                s.add(i)
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0

    def test_should_not_create_stringobject_with_sets(self):
        def main(n):
            i = 0
            s = set()
            while i < n:
                s.add(str(i))
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0

    def test_should_not_create_intobject_with_lists(self):
        def main(n):
            i = 0
            l = []
            while i < n:
                l.append(i)
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0

    def test_should_not_create_stringobject_with_lists(self):
        def main(n):
            i = 0
            l = []
            while i < n:
                l.append(str(i))
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0

    def test_optimized_create_list_from_string(self):
        def main(n):
            i = 0
            l = []
            while i < n:
                l = list("abc" * i)
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0

    def test_optimized_create_set_from_list(self):
        def main(n):
            i = 0
            while i < n:
                s = set([1,2,3])
                i += 1
        log = self.run(main, [1000])
        assert log.result == main(1000)
        loop, = log.loops_by_filename(self.filepath)
        opnames = log.opnames(loop.allops())
        assert opnames.count('new_with_vtable') == 0
