from rpython.rlib.rbigint import rbigint
from rpython.rlib.rarithmetic import r_uint
from pypy.interpreter.error import OperationError
from pypy.objspace.std import newformat
from pypy.objspace.std.model import registerimplementation, W_Object
from pypy.objspace.std.register_all import register_all
from pypy.objspace.std.intobject import W_IntObject

class W_BoolObject(W_Object):
    from pypy.objspace.std.booltype import bool_typedef as typedef
    _immutable_fields_ = ['boolval']

    def __init__(w_self, boolval):
        w_self.boolval = not not boolval
#        w_self.taints = set()

    def __nonzero__(w_self):
        raise Exception, "you cannot do that, you must use space.is_true()"

    def __repr__(w_self):
        """ representation for debugging purposes """
        return "%s(%s)" % (w_self.__class__.__name__, w_self.boolval)

    def unwrap(w_self, space):
        return w_self.boolval

    def int_w(w_self, space):
        return int(w_self.boolval)

    def uint_w(w_self, space):
        intval = int(w_self.boolval)
        return r_uint(intval)

    def bigint_w(w_self, space):
        return rbigint.fromint(int(w_self.boolval))


registerimplementation(W_BoolObject)

W_BoolObject.w_False = W_BoolObject(False)
W_BoolObject.w_True  = W_BoolObject(True)

# bool-to-int delegation requires translating the .boolvar attribute
# to an .intval one
def delegate_Bool2IntObject(space, w_bool):
    return W_IntObject(int(w_bool.boolval))

def delegate_Bool2SmallInt(space, w_bool):
    from pypy.objspace.std.smallintobject import W_SmallIntObject
    return W_SmallIntObject(int(w_bool.boolval))   # cannot overflow


def nonzero__Bool(space, w_bool):
    return w_bool

def repr__Bool(space, w_bool):
    if w_bool.boolval:
        return space.wrap('True')
    else:
        return space.wrap('False')

def and__Bool_Bool(space, w_bool1, w_bool2):
    return space.newbool(w_bool1.boolval & w_bool2.boolval)

def or__Bool_Bool(space, w_bool1, w_bool2):
    return space.newbool(w_bool1.boolval | w_bool2.boolval)

def xor__Bool_Bool(space, w_bool1, w_bool2):
    return space.newbool(w_bool1.boolval ^ w_bool2.boolval)

str__Bool = repr__Bool

def format__Bool_ANY(space, w_bool, w_format_spec):
    return newformat.run_formatter(
            space, w_format_spec, "format_int_or_long", w_bool,
            newformat.INT_KIND)

register_all(vars())
