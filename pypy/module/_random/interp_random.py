from pypy.interpreter.error import OperationError
from pypy.interpreter.typedef import TypeDef
from pypy.interpreter.gateway import interp2app, unwrap_spec
from pypy.interpreter.baseobjspace import Wrappable
from rpython.rlib.rarithmetic import r_uint, intmask
from rpython.rlib import rbigint, rrandom, rstring

import time

def descr_new__(space, w_subtype, __args__):
    w_anything = __args__.firstarg()
    x = space.allocate_instance(W_Random, w_subtype)
    x = space.interp_w(W_Random, x)
    W_Random.__init__(x, space, w_anything)
    return space.wrap(x)

class W_Random(Wrappable):
    def __init__(self, space, w_anything):
        self._rnd = rrandom.Random()
        self.seed(space, w_anything)

    def random(self, space):
        return space.newfloat(self._rnd.random())

    def seed(self, space, w_n=None):
        if w_n is None:
            w_n = space.newint(int(time.time()))
        else:
            if space.is_true(space.isinstance(w_n, space.w_int)):
                w_n = space.abs(w_n)
            elif space.is_true(space.isinstance(w_n, space.w_long)):
                w_n = space.abs(w_n)
            else:
                # XXX not perfectly like CPython
                w_n = space.abs(space.hash(w_n))
        key = []
        w_one = space.newint(1)
        w_two = space.newint(2)
        w_thirtytwo = space.newint(32)
        # 0xffffffff
        w_masklower = space.sub(space.pow(w_two, w_thirtytwo, space.w_None),
                                w_one)
        while space.is_true(w_n):
            w_chunk = space.and_(w_n, w_masklower)
            chunk = space.uint_w(w_chunk)
            key.append(chunk)
            w_n = space.rshift(w_n, w_thirtytwo)
        if not key:
            key = [r_uint(0)]
        self._rnd.init_by_array(key)

    def getstate(self, space):
        state = [None] * (rrandom.N + 1)
        for i in range(rrandom.N):
            state[i] = space.newint(intmask(self._rnd.state[i]))
        state[rrandom.N] = space.newint(self._rnd.index)
        return space.newtuple(state)

    def setstate(self, space, w_state):
        if not space.is_true(space.isinstance(w_state, space.w_tuple)):
            errstring = space.wrap("state vector must be tuple")
            raise OperationError(space.w_TypeError, errstring)
        if space.len_w(w_state) != rrandom.N + 1:
            errstring = space.wrap("state vector is the wrong size")
            raise OperationError(space.w_ValueError, errstring)
        w_zero = space.newint(0)
        # independent of platfrom, since the below condition is only
        # true on 32 bit platforms anyway
        w_add = space.pow(space.newint(2), space.newint(32), space.w_None)
        for i in range(rrandom.N):
            w_item = space.getitem(w_state, space.newint(i))
            if space.is_true(space.lt(w_item, w_zero)):
                w_item = space.add(w_item, w_add)
            self._rnd.state[i] = space.uint_w(w_item)
        w_item = space.getitem(w_state, space.newint(rrandom.N))
        self._rnd.index = space.int_w(w_item)

    def jumpahead(self, space, w_n):
        if space.is_true(space.isinstance(w_n, space.w_long)):
            num = space.bigint_w(w_n)
            n = intmask(num.uintmask())
        else:
            n = space.int_w(w_n)
        self._rnd.jumpahead(n)

    @unwrap_spec(k=int)
    def getrandbits(self, space, k):
        if k <= 0:
            strerror = space.wrap("number of bits must be greater than zero")
            raise OperationError(space.w_ValueError, strerror)
        bytes = ((k - 1) // 32 + 1) * 4
        bytesarray = rstring.StringBuilder(bytes)
        for i in range(0, bytes, 4):
            r = self._rnd.genrand32()
            if k < 32:
                r >>= (32 - k)
            bytesarray.append(chr(r & r_uint(0xff)))
            bytesarray.append(chr((r >> 8) & r_uint(0xff)))
            bytesarray.append(chr((r >> 16) & r_uint(0xff)))
            bytesarray.append(chr((r >> 24) & r_uint(0xff)))
            k -= 32

        # little endian order to match bytearray assignment order
        result = rbigint.rbigint.frombytes(
            bytesarray.build(), 'little', signed=False)
        return space.newlong_from_rbigint(result)


W_Random.typedef = TypeDef("Random",
    __new__ = interp2app(descr_new__),
    random = interp2app(W_Random.random),
    seed = interp2app(W_Random.seed),
    getstate = interp2app(W_Random.getstate),
    setstate = interp2app(W_Random.setstate),
    jumpahead = interp2app(W_Random.jumpahead),
    getrandbits = interp2app(W_Random.getrandbits),
)
