from pypy.module.thread.test.support import GenericTestThread

class AppTestFork(GenericTestThread):
    def test_fork_with_thread(self):
        # XXX This test depends on a multicore machine, as busy_thread must
        # aquire the GIL the instant that the main thread releases it.
        # It will incorrectly pass if the GIL is not grabbed in time.
        import thread
        import os
        import time

        if not hasattr(os, 'fork'):
            skip("No fork on this platform")

        def busy_thread():
            while run:
                time.sleep(0)
            done.append(None)

        for i in range(1):
            run = True
            done = []
            try:
                thread.start_new(busy_thread, ())
                print 'sleep'

                pid = os.fork()
                if pid == 0:
                    os._exit(0)
                else:
                    self.timeout_killer(pid, 5)
                    exitcode = os.waitpid(pid, 0)[1]
                    assert exitcode == 0 # if 9, process was killed by timer!
            finally:
                run = False
                self.waitfor(lambda: done)
                assert done

    def test_forked_can_thread(self):
        "Checks that a forked interpreter can start a thread"
        import thread
        import os

        if not hasattr(os, 'fork'):
            skip("No fork on this platform")

        for i in range(10):
            # pre-allocate some locks
            thread.start_new_thread(lambda: None, ())
            print 'sleep'

            pid = os.fork()
            if pid == 0:
                thread.start_new_thread(lambda: None, ())
                os._exit(0)
            else:
                self.timeout_killer(pid, 5)
                exitcode = os.waitpid(pid, 0)[1]
                assert exitcode == 0 # if 9, process was killed by timer!
