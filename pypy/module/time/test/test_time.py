import time

class TestTime: 
    spaceconfig = dict(usemodules=['time'])

    def test_clock(self, space):
        t0 = time.clock()
        w_t1 = space.appexec([], """(): import time; return time.clock()""")
        t2 = time.clock()
        assert t0 <= space.unwrap(w_t1) <= t2

    def test_time(self, space):
        t0 = time.time()
        w_t1 = space.appexec([], """(): import time; return time.time()""")
        t2 = time.time()
        assert t0 <= space.unwrap(w_t1) <= t2

    def test_sleep(self, space):
        w_sleep = space.appexec([], """(): import time; return time.sleep""")
        t0 = time.time()
        space.call_function(w_sleep, space.wrap(0.3))
        t1 = time.time()
        assert t1-t0 > 0.25
