import thread, errno
from rpython.rlib.rsocket import *
from rpython.rlib.rpoll import *
from rpython.rtyper.test.test_llinterp import interpret

def setup_module(mod):
    rsocket_startup()

def test_simple():
    serv = RSocket(AF_INET, SOCK_STREAM)
    serv.bind(INETAddress('127.0.0.1', INADDR_ANY))
    serv.listen(1)
    servaddr = serv.getsockname()

    events = poll({serv.fd: POLLIN}, timeout=100)
    assert len(events) == 0

    cli = RSocket(AF_INET, SOCK_STREAM)
    cli.setblocking(False)
    err = cli.connect_ex(servaddr)
    assert err != 0

    events = poll({serv.fd: POLLIN}, timeout=500)
    assert len(events) == 1
    assert events[0][0] == serv.fd
    assert events[0][1] & POLLIN

    servconn_fd, cliaddr = serv.accept()
    servconn = RSocket(AF_INET, fd=servconn_fd)

    events = poll({serv.fd: POLLIN,
                   cli.fd: POLLOUT}, timeout=500)
    assert len(events) == 1
    assert events[0][0] == cli.fd
    assert events[0][1] & POLLOUT

    err = cli.connect_ex(servaddr)
    # win32: returns WSAEISCONN when the connection finally succeed.
    # Mac OS/X: returns EISCONN.
    assert (err == 0 or err == 10056 or
            err == getattr(errno, 'EISCONN', '???'))

    events = poll({servconn.fd: POLLIN,
                   cli.fd: POLLIN}, timeout=100)
    assert len(events) == 0

    events = poll({servconn.fd: POLLOUT,
                   cli.fd: POLLOUT}, timeout=100)
    assert len(events) >= 1

    cli.close()
    servconn.close()
    serv.close()

def test_select():
    def f():
        readend, writeend = os.pipe()
        try:
            iwtd, owtd, ewtd = select([readend], [], [], 0.0)
            assert iwtd == owtd == ewtd == []
            os.write(writeend, 'X')
            iwtd, owtd, ewtd = select([readend], [], [])
            assert iwtd == [readend]
            assert owtd == ewtd == []

        finally:
            os.close(readend)
            os.close(writeend)
    f()
    interpret(f, [])

def test_select_timeout():
    from time import time
    def f():
        # once there was a bug where the sleeping time was doubled
        a = time()
        iwtd, owtd, ewtd = select([], [], [], 5.0)
        diff = time() - a
        assert 4.8 < diff < 9.0
    interpret(f, [])


def test_translate():
    from rpython.translator.c.test.test_genc import compile

    def func():
        poll({})

    compile(func, [])
