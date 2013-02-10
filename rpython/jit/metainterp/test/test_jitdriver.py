"""Tests for multiple JitDrivers."""
from rpython.rlib.jit import JitDriver, unroll_safe, set_param
from rpython.jit.metainterp.test.support import LLJitMixin, OOJitMixin
from rpython.jit.metainterp.warmspot import get_stats


def getloc1():
    return "in jitdriver1"

def getloc2(g):
    return "in jitdriver2, with g=%d" % g

class MultipleJitDriversTests(object):

    def test_simple(self):
        myjitdriver1 = JitDriver(greens=[], reds=['n', 'm'],
                                 get_printable_location = getloc1)
        myjitdriver2 = JitDriver(greens=['g'], reds=['r'],
                                 get_printable_location = getloc2)
        #
        def loop1(n, m):
            while n > 0:
                myjitdriver1.can_enter_jit(n=n, m=m)
                myjitdriver1.jit_merge_point(n=n, m=m)
                n -= m
            return n
        #
        def loop2(g, r):
            while r > 0:
                myjitdriver2.can_enter_jit(g=g, r=r)
                myjitdriver2.jit_merge_point(g=g, r=r)
                r += loop1(r, g) + (-1)
            return r
        #
        res = self.meta_interp(loop2, [4, 40], repeat=7, inline=True)
        assert res == loop2(4, 40)
        # we expect only one int_sub, corresponding to the single
        # compiled instance of loop1()
        self.check_resops(int_sub=2)
        # the following numbers are not really expectations of the test
        # itself, but just the numbers that we got after looking carefully
        # at the generated machine code
        self.check_trace_count(5)
        self.check_jitcell_token_count(2)    # 2 x loop including enter bridge
        self.check_target_token_count(4)    # 2 x loop, 2 x enter bridge
        self.check_enter_count(5)

    def test_inline(self):
        # this is not an example of reasonable code: loop1() is unrolled
        # 'n/m' times, where n and m are given as red arguments.
        myjitdriver1 = JitDriver(greens=[], reds=['n', 'm'],
                                 get_printable_location = getloc1)
        myjitdriver2 = JitDriver(greens=['g'], reds=['r'],
                                 get_printable_location = getloc2)
        #
        def loop1(n, m):
            while n > 0:
                if n > 1000:
                    myjitdriver1.can_enter_jit(n=n, m=m)
                myjitdriver1.jit_merge_point(n=n, m=m)
                n -= m
            return n
        #
        def loop2(g, r):
            set_param(None, 'function_threshold', 0)
            while r > 0:
                myjitdriver2.can_enter_jit(g=g, r=r)
                myjitdriver2.jit_merge_point(g=g, r=r)
                r += loop1(r, g) - 1
            return r
        #
        res = self.meta_interp(loop2, [4, 40], repeat=7, inline=True)
        assert res == loop2(4, 40)
        # we expect no loop at all for 'loop1': it should always be inlined
        # we do however get several version of 'loop2', all of which contains
        # at least one int_add, while there are no int_add's in 'loop1'
        self.check_jitcell_token_count(1)
        for loop in get_stats().loops:
            assert loop.summary()['int_add'] >= 1

    def test_inactive_jitdriver(self):
        myjitdriver1 = JitDriver(greens=[], reds=['n', 'm'],
                                 get_printable_location = getloc1)
        myjitdriver2 = JitDriver(greens=['g'], reds=['r'],
                                 get_printable_location = getloc2)
        #
        myjitdriver1.active = False    # <===
        #
        def loop1(n, m):
            while n > 0:
                myjitdriver1.can_enter_jit(n=n, m=m)
                myjitdriver1.jit_merge_point(n=n, m=m)
                n -= m
            return n
        #
        def loop2(g, r):
            while r > 0:
                myjitdriver2.can_enter_jit(g=g, r=r)
                myjitdriver2.jit_merge_point(g=g, r=r)
                r += loop1(r, g) + (-1)
            return r
        #
        res = self.meta_interp(loop2, [4, 40], repeat=7, inline=True)
        assert res == loop2(4, 40)
        # we expect no int_sub, but a residual call
        self.check_resops(call=2, int_sub=0)

    def test_multiple_jits_trace_too_long(self):
        myjitdriver1 = JitDriver(greens=["n"], reds=["i", "box"])
        myjitdriver2 = JitDriver(greens=["n"], reds=["i"])

        class IntBox(object):
            def __init__(self, val):
                self.val = val

        def loop1(n):
            i = 0
            box = IntBox(10)
            while i < n:
                myjitdriver1.can_enter_jit(n=n, i=i, box=box)
                myjitdriver1.jit_merge_point(n=n, i=i, box=box)
                i += 1
                loop2(box)
            return i

        def loop2(n):
            i = 0
            f(10)
            while i < n.val:
                myjitdriver2.can_enter_jit(n=n, i=i)
                myjitdriver2.jit_merge_point(n=n, i=i)
                i += 1

        @unroll_safe
        def f(n):
            i = 0
            while i < n:
                i += 1

        res = self.meta_interp(loop1, [10], inline=True, trace_limit=6)
        assert res == 10
        stats = get_stats()
        assert stats.aborted_keys == [None, None]


class TestLLtype(MultipleJitDriversTests, LLJitMixin):
    pass

class TestOOtype(MultipleJitDriversTests, OOJitMixin):
    pass
