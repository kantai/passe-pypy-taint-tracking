import sys
import py
from pypy.tool.pytest.objspace import gettestobjspace
from rpython.tool.udir import udir
from rpython.rlib import rsocket
from rpython.rtyper.lltypesystem import lltype, rffi

def setup_module(mod):
    mod.space = gettestobjspace(usemodules=['_socket', 'array', 'struct'])
    global socket
    import socket
    mod.w_socket = space.appexec([], "(): import _socket as m; return m")
    mod.path = udir.join('fd')
    mod.path.write('fo')
    mod.raises = py.test.raises # make raises available from app-level tests
    mod.skip = py.test.skip

def test_gethostname():
    host = space.appexec([w_socket], "(_socket): return _socket.gethostname()")
    assert space.unwrap(host) == socket.gethostname()

def test_gethostbyname():
    host = "localhost"
    ip = space.appexec([w_socket, space.wrap(host)],
                       "(_socket, host): return _socket.gethostbyname(host)")
    assert space.unwrap(ip) == socket.gethostbyname(host)

def test_gethostbyname_ex():
    host = "localhost"
    ip = space.appexec([w_socket, space.wrap(host)],
                       "(_socket, host): return _socket.gethostbyname_ex(host)")
    assert isinstance(space.unwrap(ip), tuple)
    assert space.unwrap(ip) == socket.gethostbyname_ex(host)

def test_gethostbyaddr():
    host = "localhost"
    expected = socket.gethostbyaddr(host)
    expecteds = (expected, expected[:2]+(['0.0.0.0'],))
    ip = space.appexec([w_socket, space.wrap(host)],
                       "(_socket, host): return _socket.gethostbyaddr(host)")
    assert space.unwrap(ip) in expecteds
    host = "127.0.0.1"
    expected = socket.gethostbyaddr(host)
    expecteds = (expected, expected[:2]+(['0.0.0.0'],))
    ip = space.appexec([w_socket, space.wrap(host)],
                       "(_socket, host): return _socket.gethostbyaddr(host)")
    assert space.unwrap(ip) in expecteds

def test_getservbyname():
    name = "smtp"
    # 2 args version
    port = space.appexec([w_socket, space.wrap(name)],
                        "(_socket, name): return _socket.getservbyname(name, 'tcp')")
    assert space.unwrap(port) == 25
    # 1 arg version
    if sys.version_info < (2, 4):
        py.test.skip("getservbyname second argument is not optional before python 2.4")
    port = space.appexec([w_socket, space.wrap(name)],
                        "(_socket, name): return _socket.getservbyname(name)")
    assert space.unwrap(port) == 25

def test_getservbyport():
    if sys.version_info < (2, 4):
        py.test.skip("getservbyport does not exist before python 2.4")
    port = 25
    # 2 args version
    name = space.appexec([w_socket, space.wrap(port)],
                         "(_socket, port): return _socket.getservbyport(port, 'tcp')")
    assert space.unwrap(name) == "smtp"
    name = space.appexec([w_socket, space.wrap(port)],
                         """(_socket, port):
                         try:
                             return _socket.getservbyport(port, 42)
                         except TypeError:
                             return 'OK'
                         """)
    assert space.unwrap(name) == 'OK'
    # 1 arg version
    name = space.appexec([w_socket, space.wrap(port)],
                         "(_socket, port): return _socket.getservbyport(port)")
    assert space.unwrap(name) == "smtp"

    from pypy.interpreter.error import OperationError
    exc = raises(OperationError, space.appexec,
           [w_socket], "(_socket): return _socket.getservbyport(-1)")
    assert exc.value.match(space, space.w_ValueError)

def test_getprotobyname():
    name = "tcp"
    w_n = space.appexec([w_socket, space.wrap(name)],
                        "(_socket, name): return _socket.getprotobyname(name)")
    assert space.unwrap(w_n) == socket.IPPROTO_TCP

def test_fromfd():
    # XXX review
    if not hasattr(socket, 'fromfd'):
        py.test.skip("No socket.fromfd on this platform")
    orig_fd = path.open()
    fd = space.appexec([w_socket, space.wrap(orig_fd.fileno()),
            space.wrap(socket.AF_INET), space.wrap(socket.SOCK_STREAM),
            space.wrap(0)],
           """(_socket, fd, family, type, proto): 
                 return _socket.fromfd(fd, family, type, proto)""")

    assert space.unwrap(space.call_method(fd, 'fileno'))
    fd = space.appexec([w_socket, space.wrap(orig_fd.fileno()),
            space.wrap(socket.AF_INET), space.wrap(socket.SOCK_STREAM)],
                """(_socket, fd, family, type):
                    return _socket.fromfd(fd, family, type)""")

    assert space.unwrap(space.call_method(fd, 'fileno'))

def test_ntohs():
    w_n = space.appexec([w_socket, space.wrap(125)],
                        "(_socket, x): return _socket.ntohs(x)")
    assert space.unwrap(w_n) == socket.ntohs(125)

def test_ntohl():
    w_n = space.appexec([w_socket, space.wrap(125)],
                        "(_socket, x): return _socket.ntohl(x)")
    assert space.unwrap(w_n) == socket.ntohl(125)
    w_n = space.appexec([w_socket, space.wrap(0x89abcdef)],
                        "(_socket, x): return _socket.ntohl(x)")
    assert space.unwrap(w_n) in (0x89abcdef, 0xefcdab89)
    space.raises_w(space.w_OverflowError, space.appexec,
                   [w_socket, space.wrap(1<<32)],
                   "(_socket, x): return _socket.ntohl(x)")

def test_htons():
    w_n = space.appexec([w_socket, space.wrap(125)],
                        "(_socket, x): return _socket.htons(x)")
    assert space.unwrap(w_n) == socket.htons(125)

def test_htonl():
    w_n = space.appexec([w_socket, space.wrap(125)],
                        "(_socket, x): return _socket.htonl(x)")
    assert space.unwrap(w_n) == socket.htonl(125)
    w_n = space.appexec([w_socket, space.wrap(0x89abcdef)],
                        "(_socket, x): return _socket.htonl(x)")
    assert space.unwrap(w_n) in (0x89abcdef, 0xefcdab89)
    space.raises_w(space.w_OverflowError, space.appexec,
                   [w_socket, space.wrap(1<<32)],
                   "(_socket, x): return _socket.htonl(x)")

def test_aton_ntoa():
    ip = '123.45.67.89'
    packed = socket.inet_aton(ip)
    w_p = space.appexec([w_socket, space.wrap(ip)],
                        "(_socket, ip): return _socket.inet_aton(ip)")
    assert space.unwrap(w_p) == packed
    w_ip = space.appexec([w_socket, space.wrap(packed)],
                         "(_socket, p): return _socket.inet_ntoa(p)")
    assert space.unwrap(w_ip) == ip

def test_pton_ntop_ipv4():
    if not hasattr(socket, 'inet_pton'):
        py.test.skip('No socket.inet_pton on this platform')
    tests = [
        ("123.45.67.89", "\x7b\x2d\x43\x59"),
        ("0.0.0.0", "\x00" * 4),
        ("255.255.255.255", "\xff" * 4),
    ]
    for ip, packed in tests:
        w_p = space.appexec([w_socket, space.wrap(ip)],
                            "(_socket, ip): return _socket.inet_pton(_socket.AF_INET, ip)")
        assert space.unwrap(w_p) == packed
        w_ip = space.appexec([w_socket, w_p],
                             "(_socket, p): return _socket.inet_ntop(_socket.AF_INET, p)")
        assert space.unwrap(w_ip) == ip

def test_ntop_ipv6():
    if not hasattr(socket, 'inet_pton'):
        py.test.skip('No socket.inet_pton on this platform')
    if not socket.has_ipv6:
        py.test.skip("No IPv6 on this platform")
    tests = [
        ("\x00" * 16, "::"),
        ("\x01" * 16, ":".join(["101"] * 8)),
        ("\x00\x00\x10\x10" * 4, None), #"::1010:" + ":".join(["0:1010"] * 3)),
        ("\x00" * 12 + "\x01\x02\x03\x04", "::1.2.3.4"),
        ("\x00" * 10 + "\xff\xff\x01\x02\x03\x04", "::ffff:1.2.3.4"),
    ]
    for packed, ip in tests:
        w_ip = space.appexec([w_socket, space.wrap(packed)],
            "(_socket, packed): return _socket.inet_ntop(_socket.AF_INET6, packed)")
        if ip is not None:   # else don't check for the precise representation
            assert space.unwrap(w_ip) == ip
        w_packed = space.appexec([w_socket, w_ip],
            "(_socket, ip): return _socket.inet_pton(_socket.AF_INET6, ip)")
        assert space.unwrap(w_packed) == packed

def test_pton_ipv6():
    if not hasattr(socket, 'inet_pton'):
        py.test.skip('No socket.inet_pton on this platform')
    if not socket.has_ipv6:
        py.test.skip("No IPv6 on this platform")
    tests = [
        ("\x00" * 16, "::"),
        ("\x01" * 16, ":".join(["101"] * 8)),
        ("\x00\x01" + "\x00" * 12 + "\x00\x02", "1::2"),
        ("\x00" * 4 + "\x00\x01" * 6, "::1:1:1:1:1:1"),
        ("\x00\x01" * 6 + "\x00" * 4, "1:1:1:1:1:1::"),
        ("\xab\xcd\xef\00" + "\x00" * 12, "ABCD:EF00::"),
        ("\xab\xcd\xef\00" + "\x00" * 12, "abcd:ef00::"),
        ("\x00\x00\x10\x10" * 4, "::1010:" + ":".join(["0:1010"] * 3)),
        ("\x00" * 12 + "\x01\x02\x03\x04", "::1.2.3.4"),
        ("\x00" * 10 + "\xff\xff\x01\x02\x03\x04", "::ffff:1.2.3.4"),
    ]
    for packed, ip in tests:
        w_packed = space.appexec([w_socket, space.wrap(ip)],
            "(_socket, ip): return _socket.inet_pton(_socket.AF_INET6, ip)")
        assert space.unwrap(w_packed) == packed

def test_has_ipv6():
    py.test.skip("has_ipv6 is always True on PyPy for now")
    res = space.appexec([w_socket], "(_socket): return _socket.has_ipv6")
    assert space.unwrap(res) == socket.has_ipv6

def test_getaddrinfo():
    host = "localhost"
    port = 25
    info = socket.getaddrinfo(host, port)
    w_l = space.appexec([w_socket, space.wrap(host), space.wrap(port)],
                        "(_socket, host, port): return _socket.getaddrinfo(host, port)")
    assert space.unwrap(w_l) == info
    py.test.skip("Unicode conversion is too slow")
    w_l = space.appexec([w_socket, space.wrap(unicode(host)), space.wrap(port)],
                        "(_socket, host, port): return _socket.getaddrinfo(host, port)")
    assert space.unwrap(w_l) == info

def test_unknown_addr_as_object():    
    from pypy.module._socket.interp_socket import addr_as_object
    c_addr = lltype.malloc(rsocket._c.sockaddr, flavor='raw')
    c_addr.c_sa_data[0] = 'c'
    rffi.setintfield(c_addr, 'c_sa_family', 15)
    # XXX what size to pass here? for the purpose of this test it has
    #     to be short enough so we have some data, 1 sounds good enough
    #     + sizeof USHORT
    w_obj = addr_as_object(rsocket.Address(c_addr, 1 + 2), -1, space)
    assert space.is_true(space.isinstance(w_obj, space.w_tuple))
    assert space.int_w(space.getitem(w_obj, space.wrap(0))) == 15
    assert space.str_w(space.getitem(w_obj, space.wrap(1))) == 'c'

def test_addr_raw_packet():
    from pypy.module._socket.interp_socket import addr_as_object
    if not hasattr(rsocket._c, 'sockaddr_ll'):
        py.test.skip("posix specific test")
    # HACK: To get the correct interface numer of lo, which in most cases is 1,
    # but can be anything (i.e. 39), we need to call the libc function
    # if_nametoindex to get the correct index
    import ctypes
    libc = ctypes.CDLL(ctypes.util.find_library('c'))
    ifnum = libc.if_nametoindex('lo')

    c_addr_ll = lltype.malloc(rsocket._c.sockaddr_ll, flavor='raw')
    addrlen = rffi.sizeof(rsocket._c.sockaddr_ll)
    c_addr = rffi.cast(lltype.Ptr(rsocket._c.sockaddr), c_addr_ll)
    rffi.setintfield(c_addr_ll, 'c_sll_ifindex', ifnum)
    rffi.setintfield(c_addr_ll, 'c_sll_protocol', 8)
    rffi.setintfield(c_addr_ll, 'c_sll_pkttype', 13)
    rffi.setintfield(c_addr_ll, 'c_sll_hatype', 0)
    rffi.setintfield(c_addr_ll, 'c_sll_halen', 3)
    c_addr_ll.c_sll_addr[0] = 'a'
    c_addr_ll.c_sll_addr[1] = 'b'
    c_addr_ll.c_sll_addr[2] = 'c'
    rffi.setintfield(c_addr, 'c_sa_family', socket.AF_PACKET)
    # fd needs to be somehow valid
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fd = s.fileno()
    w_obj = addr_as_object(rsocket.make_address(c_addr, addrlen), fd, space)
    lltype.free(c_addr_ll, flavor='raw')
    assert space.is_true(space.eq(w_obj, space.newtuple([
        space.wrap('lo'),
        space.wrap(socket.ntohs(8)),
        space.wrap(13),
        space.wrap(False),
        space.wrap("abc"),
        ])))

def test_getnameinfo():
    host = "127.0.0.1"
    port = 25
    info = socket.getnameinfo((host, port), 0)
    w_l = space.appexec([w_socket, space.wrap(host), space.wrap(port)],
                        "(_socket, host, port): return _socket.getnameinfo((host, port), 0)")
    assert space.unwrap(w_l) == info

def test_timeout():
    space.appexec([w_socket, space.wrap(25.4)],
                  "(_socket, timeout): _socket.setdefaulttimeout(timeout)")
    w_t = space.appexec([w_socket],
                  "(_socket): return _socket.getdefaulttimeout()")
    assert space.unwrap(w_t) == 25.4

    space.appexec([w_socket, space.w_None],
                  "(_socket, timeout): _socket.setdefaulttimeout(timeout)")
    w_t = space.appexec([w_socket],
                  "(_socket): return _socket.getdefaulttimeout()")
    assert space.unwrap(w_t) is None


# XXX also need tests for other connection and timeout errors


class AppTestSocket:
    def setup_class(cls):
        cls.space = space
        cls.w_udir = space.wrap(str(udir))

    def test_ntoa_exception(self):
        import _socket
        raises(_socket.error, _socket.inet_ntoa, "ab")

    def test_aton_exceptions(self):
        import _socket
        tests = ["127.0.0.256", "127.0.0.255555555555555555", "127.2b.0.0",
            "127.2.0.0.1", "127.2.0."]
        for ip in tests:
            raises(_socket.error, _socket.inet_aton, ip)

    def test_ntop_exceptions(self):
        import _socket
        if not hasattr(_socket, 'inet_ntop'):
            skip('No socket.inet_pton on this platform')
        for family, packed, exception in \
                    [(_socket.AF_INET + _socket.AF_INET6, "", _socket.error),
                     (_socket.AF_INET, "a", ValueError),
                     (_socket.AF_INET6, "a", ValueError),
                     (_socket.AF_INET, u"aa\u2222a", UnicodeEncodeError)]:
            raises(exception, _socket.inet_ntop, family, packed)

    def test_pton_exceptions(self):
        import _socket
        if not hasattr(_socket, 'inet_pton'):
            skip('No socket.inet_pton on this platform')
        tests = [
            (_socket.AF_INET + _socket.AF_INET6, ""),
            (_socket.AF_INET, "127.0.0.256"),
            (_socket.AF_INET, "127.0.0.255555555555555555"),
            (_socket.AF_INET, "127.2b.0.0"),
            (_socket.AF_INET, "127.2.0.0.1"),
            (_socket.AF_INET, "127.2..0"),
            (_socket.AF_INET6, "127.0.0.1"),
            (_socket.AF_INET6, "1::2::3"),
            (_socket.AF_INET6, "1:1:1:1:1:1:1:1:1"),
            (_socket.AF_INET6, "1:1:1:1:1:1:1:1::"),
            (_socket.AF_INET6, "1:1:1::1:1:1:1:1"),
            (_socket.AF_INET6, "1::22222:1"),
            (_socket.AF_INET6, "1::eg"),
        ]
        for family, ip in tests:
            raises(_socket.error, _socket.inet_pton, family, ip)

    def test_newsocket_error(self):
        import _socket
        raises(_socket.error, _socket.socket, 10001, _socket.SOCK_STREAM, 0)

    def test_socket_fileno(self):
        import _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        assert s.fileno() > -1
        assert isinstance(s.fileno(), int)

    def test_socket_close(self):
        import _socket, os
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        fileno = s.fileno()
        assert s.fileno() >= 0
        s.close()
        assert s.fileno() < 0
        s.close()
        if os.name != 'nt':
            raises(OSError, os.close, fileno)

    def test_socket_close_error(self):
        import _socket, os
        if os.name == 'nt':
            skip("Windows sockets are not files")
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        os.close(s.fileno())
        s.close()

    def test_socket_connect(self):
        import _socket, os
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        # it would be nice to have a test which works even if there is no
        # network connection. However, this one is "good enough" for now. Skip
        # it if there is no connection.
        try:
            s.connect(("www.python.org", 80))
        except _socket.gaierror, ex:
            skip("GAIError - probably no connection: %s" % str(ex.args))
        name = s.getpeername() # Will raise socket.error if not connected
        assert name[1] == 80
        s.close()
    
    def test_socket_connect_ex(self):
        import _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        # Make sure we get an app-level error, not an interp one.
        raises(_socket.gaierror, s.connect_ex, ("wrong.invalid", 80))
        s.close()

    def test_socket_connect_typeerrors(self):
        tests = [
            "",
            ("80"),
            ("80", "80"),
            (80, 80),
        ]
        import _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        for args in tests:
            raises((TypeError, ValueError), s.connect, args)
        s.close()

    def test_bigport(self):
        import _socket
        s = _socket.socket()
        raises(ValueError, s.connect, ("localhost", 1000000))
        raises(ValueError, s.connect, ("localhost", -1))

    def test_NtoH(self):
        import sys
        import _socket as socket
        # This just checks that htons etc. are their own inverse,
        # when looking at the lower 16 or 32 bits.
        sizes = {socket.htonl: 32, socket.ntohl: 32,
                 socket.htons: 16, socket.ntohs: 16}
        for func, size in sizes.items():
            mask = (1L<<size) - 1
            for i in (0, 1, 0xffff, ~0xffff, 2, 0x01234567, 0x76543210):
                assert i & mask == func(func(i&mask)) & mask

            swapped = func(mask)
            assert swapped & mask == mask
            try:
                func(-1)
            except (OverflowError, ValueError):
                pass
            else:
                assert False
            try:
                func(sys.maxint*2+2)
            except OverflowError:
                pass
            else:
                assert False

    def test_NtoH_overflow(self):
        skip("we are not checking for overflowing values yet")
        import _socket as socket
        # Checks that we cannot give too large values to htons etc.
        # Skipped for now; CPython 2.6 is also not consistent.
        sizes = {socket.htonl: 32, socket.ntohl: 32,
                 socket.htons: 16, socket.ntohs: 16}
        for func, size in sizes.items():
            try:
                func(1L << size)
            except OverflowError:
                pass
            else:
                assert False

    def test_newsocket(self):
        import socket
        s = socket.socket()

    def test_getsetsockopt(self):
        import _socket as socket
        import struct
        # A socket sould start with reuse == 0
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        reuse = s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
        assert reuse == 0
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        reuse = s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
        assert reuse != 0
        # String case
        intsize = struct.calcsize('i')
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        reusestr = s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,
                                intsize)
        (reuse,) = struct.unpack('i', reusestr)
        assert reuse == 0
        reusestr = struct.pack('i', 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, reusestr)
        reusestr = s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,
                                intsize)
        (reuse,) = struct.unpack('i', reusestr)
        assert reuse != 0

    def test_socket_ioctl(self):
        import _socket, sys
        if sys.platform != 'win32':
            skip("win32 only")
        assert hasattr(_socket.socket, 'ioctl')
        assert hasattr(_socket, 'SIO_RCVALL')
        assert hasattr(_socket, 'RCVALL_ON')
        assert hasattr(_socket, 'RCVALL_OFF')
        assert hasattr(_socket, 'SIO_KEEPALIVE_VALS')
        s = _socket.socket()
        raises(ValueError, s.ioctl, -1, None)
        s.ioctl(_socket.SIO_KEEPALIVE_VALS, (1, 100, 100))

    def test_dup(self):
        import _socket as socket
        if not hasattr(socket.socket, 'dup'):
            skip('No dup() on this platform')
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('localhost', 0))
        s2 = s.dup()
        assert s.fileno() != s2.fileno()
        assert s.getsockname() == s2.getsockname()

    def test_buffer_or_unicode(self):
        # Test that send/sendall/sendto accept a buffer or a unicode as arg
        import _socket, os
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
        # XXX temporarily we use python.org to test, will have more robust tests
        # in the absence of a network connection later when more parts of the
        # socket API are implemented.  Currently skip the test if there is no
        # connection.
        try:
            s.connect(("www.python.org", 80))
        except _socket.gaierror, ex:
            skip("GAIError - probably no connection: %s" % str(ex.args))
        s.send(buffer(''))
        s.sendall(buffer(''))
        s.send(u'')
        s.sendall(u'')
        raises(UnicodeEncodeError, s.send, u'\xe9')
        s.close()
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM, 0)
        s.sendto(buffer(''), ('localhost', 9)) # Send to discard port.
        s.close()

    def test_unix_socket_connect(self):
        import _socket, os
        if not hasattr(_socket, 'AF_UNIX'):
            skip('AF_UNIX not supported.')
        oldcwd = os.getcwd()
        os.chdir(self.udir)
        try:
            sockpath = 'app_test_unix_socket_connect'

            serversock = _socket.socket(_socket.AF_UNIX)
            serversock.bind(sockpath)
            serversock.listen(1)

            clientsock = _socket.socket(_socket.AF_UNIX)
            clientsock.connect(sockpath)
            s, addr = serversock.accept()
            assert not addr

            s.send('X')
            data = clientsock.recv(100)
            assert data == 'X'
            clientsock.send('Y')
            data = s.recv(100)
            assert data == 'Y'

            clientsock.close()
            s.close()
        finally:
            os.chdir(oldcwd)


class AppTestSocketTCP:
    def setup_class(cls):
        cls.space = space

    HOST = 'localhost'
        
    def setup_method(self, method):
        w_HOST = space.wrap(self.HOST)
        self.w_serv = space.appexec([w_socket, w_HOST],
            '''(_socket, HOST):
            serv = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            serv.bind((HOST, 0))
            serv.listen(1)
            return serv
            ''')
    def teardown_method(self, method):
        if hasattr(self, 'w_serv'):
            space.appexec([self.w_serv], '(serv): serv.close()')
            self.w_serv = None

    def test_timeout(self):
        from _socket import timeout
        def raise_timeout():
            self.serv.settimeout(1.0)
            self.serv.accept()
        raises(timeout, raise_timeout)

    def test_timeout_zero(self):
        from _socket import error
        def raise_error():
            self.serv.settimeout(0.0)
            foo = self.serv.accept()
        raises(error, raise_error)

    def test_recv_send_timeout(self):
        from _socket import socket, timeout
        cli = socket()
        cli.connect(self.serv.getsockname())
        t, addr = self.serv.accept()
        cli.settimeout(1.0)
        # test recv() timeout
        t.send('*')
        buf = cli.recv(100)
        assert buf == '*'
        raises(timeout, cli.recv, 100)
        # test that send() works
        count = cli.send('!')
        assert count == 1
        buf = t.recv(1)
        assert buf == '!'
        # test that sendall() works
        cli.sendall('?')
        assert count == 1
        buf = t.recv(1)
        assert buf == '?'
        # test send() timeout
        count = 0
        try:
            while 1:
                count += cli.send('foobar' * 70)
        except timeout:
            pass
        t.recv(count)    
        # test sendall() timeout
        try:
            while 1:
                cli.sendall('foobar' * 70)
        except timeout:
            pass
        # done
        cli.close()
        t.close()

    def test_recv_into(self):
        import socket
        import array
        MSG = 'dupa was here\n'
        cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cli.connect(self.serv.getsockname())
        conn, addr = self.serv.accept()
        buf = buffer(MSG)
        conn.send(buf)
        buf = array.array('c', ' '*1024)
        nbytes = cli.recv_into(buf)
        assert nbytes == len(MSG)
        msg = buf.tostring()[:len(MSG)]
        assert msg == MSG

    def test_recvfrom_into(self):
        import socket
        import array
        MSG = 'dupa was here\n'
        cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cli.connect(self.serv.getsockname())
        conn, addr = self.serv.accept()
        buf = buffer(MSG)
        conn.send(buf)
        buf = array.array('c', ' '*1024)
        nbytes, addr = cli.recvfrom_into(buf)
        assert nbytes == len(MSG)
        msg = buf.tostring()[:len(MSG)]
        assert msg == MSG

    def test_family(self):
        import socket
        cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        assert cli.family == socket.AF_INET

class AppTestErrno:
    def setup_class(cls):
        cls.space = space

    def test_errno(self):
        from socket import socket, AF_INET, SOCK_STREAM, error
        import errno
        s = socket(AF_INET, SOCK_STREAM)
        exc = raises(error, s.accept)
        assert isinstance(exc.value, error)
        assert isinstance(exc.value, IOError)
        # error is EINVAL, or WSAEINVAL on Windows
        assert exc.value.errno == getattr(errno, 'WSAEINVAL', errno.EINVAL)
        assert isinstance(exc.value.message, str)
