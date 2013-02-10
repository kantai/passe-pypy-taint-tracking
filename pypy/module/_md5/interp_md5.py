from rpython.rlib import rmd5
from pypy.interpreter.baseobjspace import Wrappable
from pypy.interpreter.typedef import TypeDef
from pypy.interpreter.gateway import interp2app, unwrap_spec


class W_MD5(Wrappable, rmd5.RMD5):
    """
    A subclass of RMD5 that can be exposed to app-level.
    """

    def __init__(self, space):
        self.space = space
        self._init()

    @unwrap_spec(string='bufferstr')
    def update_w(self, string):
        self.update(string)

    def digest_w(self):
        return self.space.wrap(self.digest())

    def hexdigest_w(self):
        return self.space.wrap(self.hexdigest())

    def copy_w(self):
        clone = W_MD5(self.space)
        clone._copyfrom(self)
        return self.space.wrap(clone)


@unwrap_spec(initialdata='bufferstr')
def W_MD5___new__(space, w_subtype, initialdata=''):
    """
    Create a new md5 object and call its initializer.
    """
    w_md5 = space.allocate_instance(W_MD5, w_subtype)
    md5 = space.interp_w(W_MD5, w_md5)
    W_MD5.__init__(md5, space)
    md5.update(initialdata)
    return w_md5


W_MD5.typedef = TypeDef(
    'MD5Type',
    __new__   = interp2app(W_MD5___new__),
    update    = interp2app(W_MD5.update_w),
    digest    = interp2app(W_MD5.digest_w),
    hexdigest = interp2app(W_MD5.hexdigest_w),
    copy      = interp2app(W_MD5.copy_w),
    digest_size = 16,
    digestsize = 16,
    block_size = 64,
    __doc__   = """md5(arg) -> return new md5 object.

If arg is present, the method call update(arg) is made.""")
