from __future__ import with_statement
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.baseobjspace import Wrappable
from pypy.interpreter.gateway import interp2app, unwrap_spec
from pypy.interpreter.typedef import TypeDef
from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rdynload import DLLHANDLE, dlopen, dlsym, dlclose, DLOpenError

from pypy.module._cffi_backend.cdataobj import W_CData
from pypy.module._cffi_backend.ctypeobj import W_CType


class W_Library(Wrappable):
    _immutable_ = True
    handle = rffi.cast(DLLHANDLE, 0)

    def __init__(self, space, filename, flags):
        self.space = space
        with rffi.scoped_str2charp(filename) as ll_libname:
            if filename is None:
                filename = "<None>"
            try:
                self.handle = dlopen(ll_libname, flags)
            except DLOpenError, e:
                raise operationerrfmt(space.w_OSError,
                                      "cannot load library %s: %s",
                                      filename, e.msg)
        self.name = filename

    def __del__(self):
        h = self.handle
        if h != rffi.cast(DLLHANDLE, 0):
            self.handle = rffi.cast(DLLHANDLE, 0)
            dlclose(h)

    def repr(self):
        space = self.space
        return space.wrap("<clibrary '%s'>" % self.name)

    @unwrap_spec(ctype=W_CType, name=str)
    def load_function(self, ctype, name):
        from pypy.module._cffi_backend import ctypefunc, ctypeptr, ctypevoid
        space = self.space
        #
        ok = False
        if isinstance(ctype, ctypefunc.W_CTypeFunc):
            ok = True
        if (isinstance(ctype, ctypeptr.W_CTypePointer) and
            isinstance(ctype.ctitem, ctypevoid.W_CTypeVoid)):
            ok = True
        if not ok:
            raise operationerrfmt(space.w_TypeError,
                                  "function cdata expected, got '%s'",
                                  ctype.name)
        #
        try:
            cdata = dlsym(self.handle, name)
        except KeyError:
            raise operationerrfmt(space.w_KeyError,
                                  "function '%s' not found in library '%s'",
                                  name, self.name)
        return W_CData(space, rffi.cast(rffi.CCHARP, cdata), ctype)

    @unwrap_spec(ctype=W_CType, name=str)
    def read_variable(self, ctype, name):
        space = self.space
        try:
            cdata = dlsym(self.handle, name)
        except KeyError:
            raise operationerrfmt(space.w_KeyError,
                                  "variable '%s' not found in library '%s'",
                                  name, self.name)
        return ctype.convert_to_object(rffi.cast(rffi.CCHARP, cdata))

    @unwrap_spec(ctype=W_CType, name=str)
    def write_variable(self, ctype, name, w_value):
        space = self.space
        try:
            cdata = dlsym(self.handle, name)
        except KeyError:
            raise operationerrfmt(space.w_KeyError,
                                  "variable '%s' not found in library '%s'",
                                  name, self.name)
        ctype.convert_from_object(rffi.cast(rffi.CCHARP, cdata), w_value)


W_Library.typedef = TypeDef(
    'Library',
    __module__ = '_cffi_backend',
    __repr__ = interp2app(W_Library.repr),
    load_function = interp2app(W_Library.load_function),
    read_variable = interp2app(W_Library.read_variable),
    write_variable = interp2app(W_Library.write_variable),
    )
W_Library.acceptable_as_base_class = False


@unwrap_spec(filename="str_or_None", flags=int)
def load_library(space, filename, flags=0):
    lib = W_Library(space, filename, flags)
    return space.wrap(lib)
