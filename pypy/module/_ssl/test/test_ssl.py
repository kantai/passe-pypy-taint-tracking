class AppTestSSL:
    spaceconfig = dict(usemodules=('_ssl', '_socket'))

    def test_init_module(self):
        import _ssl
    
    def test_sslerror(self):
        import _ssl, _socket
        assert issubclass(_ssl.SSLError, Exception)
        assert issubclass(_ssl.SSLError, IOError)
        assert issubclass(_ssl.SSLError, _socket.error)

    def test_constants(self):
        import _ssl
        
        assert isinstance(_ssl.SSL_ERROR_ZERO_RETURN, int)
        assert isinstance(_ssl.SSL_ERROR_WANT_READ, int)
        assert isinstance(_ssl.SSL_ERROR_WANT_WRITE, int)
        assert isinstance(_ssl.SSL_ERROR_WANT_X509_LOOKUP, int)
        assert isinstance(_ssl.SSL_ERROR_SYSCALL, int)
        assert isinstance(_ssl.SSL_ERROR_SSL, int)
        assert isinstance(_ssl.SSL_ERROR_WANT_CONNECT, int)
        assert isinstance(_ssl.SSL_ERROR_EOF, int)
        assert isinstance(_ssl.SSL_ERROR_INVALID_ERROR_CODE, int)

        assert isinstance(_ssl.OPENSSL_VERSION_INFO, tuple)
        assert len(_ssl.OPENSSL_VERSION_INFO) == 5
        assert isinstance(_ssl.OPENSSL_VERSION, str)
        assert 'openssl' in _ssl.OPENSSL_VERSION.lower()
    
    def test_RAND_add(self):
        import _ssl
        if not hasattr(_ssl, "RAND_add"):
            skip("RAND_add is not available on this machine")
        raises(TypeError, _ssl.RAND_add, 4, 4)
        raises(TypeError, _ssl.RAND_add, "xyz", "zyx")
        _ssl.RAND_add("xyz", 1.2345)
    
    def test_RAND_status(self):
        import _ssl
        if not hasattr(_ssl, "RAND_status"):
            skip("RAND_status is not available on this machine")
        _ssl.RAND_status()
    
    def test_RAND_egd(self):
        import _ssl, os, stat
        if not hasattr(_ssl, "RAND_egd"):
            skip("RAND_egd is not available on this machine")
        raises(TypeError, _ssl.RAND_egd, 4)

        # you need to install http://egd.sourceforge.net/ to test this
        # execute "egd.pl entropy" in the current dir
        if (not os.access("entropy", 0) or
            not stat.S_ISSOCK(os.stat("entropy").st_mode)):
            skip("This test needs a running entropy gathering daemon")
        _ssl.RAND_egd("entropy")

    def test_sslwrap(self):
        import _ssl, _socket, sys, gc
        if sys.platform == 'darwin' or 'freebsd' in sys.platform:
            skip("hangs indefinitely on OSX & FreeBSD (also on CPython)")
        s = _socket.socket()
        ss = _ssl.sslwrap(s, 0)
        exc = raises(_socket.error, ss.do_handshake)
        if sys.platform == 'win32':
            assert exc.value.errno == 10057 # WSAENOTCONN
        else:
            assert exc.value.errno == 32 # Broken pipe
        del exc, ss, s
        gc.collect()     # force the destructor() to be called now

    def test_async_closed(self):
        import _ssl, _socket, gc
        s = _socket.socket()
        s.settimeout(3)
        ss = _ssl.sslwrap(s, 0)
        s.close()
        exc = raises(_ssl.SSLError, ss.write, "data")
        assert exc.value.strerror == "Underlying socket has been closed."
        del exc, ss, s
        gc.collect()     # force the destructor() to be called now


class AppTestConnectedSSL:
    spaceconfig = {
        "usemodules": ['_ssl', '_socket', 'struct', 'binascii'],
    }

    def setup_method(self, method):
        # https://www.verisign.net/
        ADDR = "www.verisign.net", 443

        self.w_s = self.space.appexec([self.space.wrap(ADDR)], """(ADDR):
            import socket
            s = socket.socket()
            try:
                s.connect(ADDR)
            except:
                skip("no network available or issues with connection")
            return s
            """)

    def test_connect(self):
        import socket, gc
        ss = socket.ssl(self.s)
        self.s.close()
        del ss; gc.collect()

    def test_server(self):
        import socket, gc
        ss = socket.ssl(self.s)
        assert isinstance(ss.server(), str)
        self.s.close()
        del ss; gc.collect()

    def test_issuer(self):
        import socket, gc
        ss = socket.ssl(self.s)
        assert isinstance(ss.issuer(), str)
        self.s.close()
        del ss; gc.collect()

    def test_write(self):
        import socket, gc
        ss = socket.ssl(self.s)
        raises(TypeError, ss.write, 123)
        num_bytes = ss.write("hello\n")
        assert isinstance(num_bytes, int)
        assert num_bytes >= 0
        self.s.close()
        del ss; gc.collect()

    def test_read(self):
        import socket, gc
        ss = socket.ssl(self.s)
        raises(TypeError, ss.read, "foo")
        ss.write("hello\n")
        data = ss.read()
        assert isinstance(data, str)
        self.s.close()
        del ss; gc.collect()

    def test_read_upto(self):
        import socket, gc
        ss = socket.ssl(self.s)
        raises(TypeError, ss.read, "foo")
        ss.write("hello\n")
        data = ss.read(10)
        assert isinstance(data, str)
        assert len(data) == 10
        assert ss.pending() > 50 # many more bytes to read
        self.s.close()
        del ss; gc.collect()

    def test_shutdown(self):
        import socket, ssl, sys, gc
        ss = socket.ssl(self.s)
        ss.write("hello\n")
        try:
            result = ss.shutdown()
        except socket.error, e:
            # xxx obscure case; throwing errno 0 is pretty odd...
            if e.errno == 0:
                skip("Shutdown raised errno 0. CPython does this too")
            raise
        assert result is self.s._sock
        raises(ssl.SSLError, ss.write, "hello\n")
        del ss; gc.collect()


class AppTestConnectedSSL_Timeout(AppTestConnectedSSL):
    # Same tests, with a socket timeout
    # to exercise the poll() calls
    spaceconfig = {
        "usemodules": ['_ssl', '_socket', 'struct', 'binascii'],
    }

    def setup_class(cls):
        cls.space.appexec([], """():
            import socket; socket.setdefaulttimeout(1)
            """)

    def teardown_class(cls):
        cls.space.appexec([], """():
            import socket; socket.setdefaulttimeout(1)
            """)
