
""" This is a set of tools for standalone compiling of numpy expressions.
It should not be imported by the module itself
"""

import re

from pypy.interpreter.baseobjspace import InternalSpaceCache, W_Root
from pypy.interpreter.error import OperationError
from pypy.module.micronumpy import interp_boxes
from pypy.module.micronumpy.interp_dtype import get_dtype_cache
from pypy.module.micronumpy.base import W_NDimArray
from pypy.module.micronumpy.interp_numarray import array
from pypy.module.micronumpy.interp_arrayops import where
from pypy.module.micronumpy import interp_ufuncs
from rpython.rlib.objectmodel import specialize, instantiate


class BogusBytecode(Exception):
    pass

class ArgumentMismatch(Exception):
    pass

class ArgumentNotAnArray(Exception):
    pass

class WrongFunctionName(Exception):
    pass

class TokenizerError(Exception):
    pass

class BadToken(Exception):
    pass

SINGLE_ARG_FUNCTIONS = ["sum", "prod", "max", "min", "all", "any",
                        "unegative", "flat", "tostring","count_nonzero"]
TWO_ARG_FUNCTIONS = ["dot", 'take']
THREE_ARG_FUNCTIONS = ['where']

class FakeSpace(object):
    w_ValueError = "ValueError"
    w_TypeError = "TypeError"
    w_IndexError = "IndexError"
    w_OverflowError = "OverflowError"
    w_NotImplementedError = "NotImplementedError"
    w_None = None

    w_bool = "bool"
    w_int = "int"
    w_float = "float"
    w_list = "list"
    w_long = "long"
    w_tuple = 'tuple'
    w_slice = "slice"
    w_str = "str"
    w_unicode = "unicode"
    w_complex = "complex"
    
    def __init__(self):
        """NOT_RPYTHON"""
        self.fromcache = InternalSpaceCache(self).getorbuild

    def _freeze_(self):
        return True

    def is_none(self, w_obj):
        return w_obj is None or w_obj is self.w_None

    def issequence_w(self, w_obj):
        return isinstance(w_obj, ListObject) or isinstance(w_obj, W_NDimArray)

    def isinstance_w(self, w_obj, w_tp):
        return w_obj.tp == w_tp

    def decode_index4(self, w_idx, size):
        if isinstance(w_idx, IntObject):
            return (self.int_w(w_idx), 0, 0, 1)
        else:
            assert isinstance(w_idx, SliceObject)
            start, stop, step = w_idx.start, w_idx.stop, w_idx.step
            if step == 0:
                return (0, size, 1, size)
            if start < 0:
                start += size
            if stop < 0:
                stop += size + 1
            if step < 0:
                lgt = (stop - start + 1) / step + 1
            else:
                lgt = (stop - start - 1) / step + 1
            return (start, stop, step, lgt)

    @specialize.argtype(1)
    def wrap(self, obj):
        if isinstance(obj, float):
            return FloatObject(obj)
        elif isinstance(obj, bool):
            return BoolObject(obj)
        elif isinstance(obj, int):
            return IntObject(obj)
        elif isinstance(obj, long):
            return LongObject(obj)
        elif isinstance(obj, W_Root):
            return obj
        elif isinstance(obj, str):
            return StringObject(obj)
        raise NotImplementedError

    def newlist(self, items):
        return ListObject(items)

    def newcomplex(self, r, i):
        return ComplexObject(r, i)

    def listview(self, obj):
        assert isinstance(obj, ListObject)
        return obj.items
    fixedview = listview

    def float(self, w_obj):
        if isinstance(w_obj, FloatObject):
            return w_obj
        assert isinstance(w_obj, interp_boxes.W_GenericBox)
        return self.float(w_obj.descr_float(self))

    def float_w(self, w_obj):
        assert isinstance(w_obj, FloatObject)
        return w_obj.floatval

    def int_w(self, w_obj):
        if isinstance(w_obj, IntObject):
            return w_obj.intval
        elif isinstance(w_obj, FloatObject):
            return int(w_obj.floatval)
        elif isinstance(w_obj, SliceObject):
            raise OperationError(self.w_TypeError, self.wrap("slice."))
        raise NotImplementedError

    def unpackcomplex(self, w_obj):
        if isinstance(w_obj, ComplexObject):
            return w_obj.r, w_obj.i
        raise NotImplementedError

    def index(self, w_obj):
        return self.wrap(self.int_w(w_obj))

    def str_w(self, w_obj):
        if isinstance(w_obj, StringObject):
            return w_obj.v
        raise NotImplementedError

    def int(self, w_obj):
        if isinstance(w_obj, IntObject):
            return w_obj
        assert isinstance(w_obj, interp_boxes.W_GenericBox)
        return self.int(w_obj.descr_int(self))

    def str(self, w_obj):
        if isinstance(w_obj, StringObject):
            return w_obj
        assert isinstance(w_obj, interp_boxes.W_GenericBox)
        return self.str(w_obj.descr_str(self))

    def is_true(self, w_obj):
        assert isinstance(w_obj, BoolObject)
        return False
        #return w_obj.boolval

    def is_w(self, w_obj, w_what):
        return w_obj is w_what

    def type(self, w_obj):
        return w_obj.tp

    def gettypefor(self, w_obj):
        return None

    def call_function(self, tp, w_dtype):
        return w_dtype

    @specialize.arg(1)
    def interp_w(self, tp, what):
        assert isinstance(what, tp)
        return what

    def allocate_instance(self, klass, w_subtype):
        return instantiate(klass)

    def newtuple(self, list_w):
        return ListObject(list_w)

    def newdict(self):
        return {}

    def setitem(self, dict, item, value):
        dict[item] = value

    def len_w(self, w_obj):
        if isinstance(w_obj, ListObject):
            return len(w_obj.items)
        # XXX array probably
        assert False

    def exception_match(self, w_exc_type, w_check_class):
        # Good enough for now
        raise NotImplementedError

class FloatObject(W_Root):
    tp = FakeSpace.w_float
    def __init__(self, floatval):
        self.floatval = floatval

class BoolObject(W_Root):
    tp = FakeSpace.w_bool
    def __init__(self, boolval):
        self.boolval = boolval

class IntObject(W_Root):
    tp = FakeSpace.w_int
    def __init__(self, intval):
        self.intval = intval

class LongObject(W_Root):
    tp = FakeSpace.w_long
    def __init__(self, intval):
        self.intval = intval

class ListObject(W_Root):
    tp = FakeSpace.w_list
    def __init__(self, items):
        self.items = items

class SliceObject(W_Root):
    tp = FakeSpace.w_slice
    def __init__(self, start, stop, step):
        self.start = start
        self.stop = stop
        self.step = step

class StringObject(W_Root):
    tp = FakeSpace.w_str
    def __init__(self, v):
        self.v = v

class ComplexObject(W_Root):
    tp = FakeSpace.w_complex
    def __init__(self, r, i):
        self.r = r
        self.i = i

class InterpreterState(object):
    def __init__(self, code):
        self.code = code
        self.variables = {}
        self.results = []

    def run(self, space):
        self.space = space
        for stmt in self.code.statements:
            stmt.execute(self)

class Node(object):
    def __eq__(self, other):
        return (self.__class__ == other.__class__ and
                self.__dict__ == other.__dict__)

    def __ne__(self, other):
        return not self == other

    def wrap(self, space):
        raise NotImplementedError

    def execute(self, interp):
        raise NotImplementedError

class Assignment(Node):
    def __init__(self, name, expr):
        self.name = name
        self.expr = expr

    def execute(self, interp):
        interp.variables[self.name] = self.expr.execute(interp)

    def __repr__(self):
        return "%r = %r" % (self.name, self.expr)

class ArrayAssignment(Node):
    def __init__(self, name, index, expr):
        self.name = name
        self.index = index
        self.expr = expr

    def execute(self, interp):
        arr = interp.variables[self.name]
        w_index = self.index.execute(interp)
        # cast to int
        if isinstance(w_index, FloatObject):
            w_index = IntObject(int(w_index.floatval))
        w_val = self.expr.execute(interp)
        assert isinstance(arr, W_NDimArray)
        arr.descr_setitem(interp.space, w_index, w_val)

    def __repr__(self):
        return "%s[%r] = %r" % (self.name, self.index, self.expr)

class Variable(Node):
    def __init__(self, name):
        self.name = name.strip(" ")

    def execute(self, interp):
        return interp.variables[self.name]

    def __repr__(self):
        return 'v(%s)' % self.name

class Operator(Node):
    def __init__(self, lhs, name, rhs):
        self.name = name
        self.lhs = lhs
        self.rhs = rhs

    def execute(self, interp):
        w_lhs = self.lhs.execute(interp)
        if isinstance(self.rhs, SliceConstant):
            w_rhs = self.rhs.wrap(interp.space)
        else:
            w_rhs = self.rhs.execute(interp)
        if not isinstance(w_lhs, W_NDimArray):
            # scalar
            dtype = get_dtype_cache(interp.space).w_float64dtype
            w_lhs = W_NDimArray.new_scalar(interp.space, dtype, w_lhs)
        assert isinstance(w_lhs, W_NDimArray)
        if self.name == '+':
            w_res = w_lhs.descr_add(interp.space, w_rhs)
        elif self.name == '*':
            w_res = w_lhs.descr_mul(interp.space, w_rhs)
        elif self.name == '-':
            w_res = w_lhs.descr_sub(interp.space, w_rhs)
        elif self.name == '->':
            if isinstance(w_rhs, FloatObject):
                w_rhs = IntObject(int(w_rhs.floatval))
            assert isinstance(w_lhs, W_NDimArray)
            w_res = w_lhs.descr_getitem(interp.space, w_rhs)
        else:
            raise NotImplementedError
        if (not isinstance(w_res, W_NDimArray) and
            not isinstance(w_res, interp_boxes.W_GenericBox)):
            dtype = get_dtype_cache(interp.space).w_float64dtype
            w_res = W_NDimArray.new_scalar(interp.space, dtype, w_res)
        return w_res

    def __repr__(self):
        return '(%r %s %r)' % (self.lhs, self.name, self.rhs)

class FloatConstant(Node):
    def __init__(self, v):
        self.v = float(v)

    def __repr__(self):
        return "Const(%s)" % self.v

    def wrap(self, space):
        return space.wrap(self.v)

    def execute(self, interp):
        return interp.space.wrap(self.v)

class ComplexConstant(Node):
    def __init__(self, r, i):
        self.r = float(r)
        self.i = float(i)

    def __repr__(self):
        return 'ComplexConst(%s, %s)' % (self.r, self.i)

    def wrap(self, space):
        return space.newcomplex(self.r, self.i)

    def execute(self, interp):
        return self.wrap(interp.space)

class RangeConstant(Node):
    def __init__(self, v):
        self.v = int(v)

    def execute(self, interp):
        w_list = interp.space.newlist(
            [interp.space.wrap(float(i)) for i in range(self.v)]
        )
        dtype = get_dtype_cache(interp.space).w_float64dtype
        return array(interp.space, w_list, w_dtype=dtype, w_order=None)

    def __repr__(self):
        return 'Range(%s)' % self.v

class Code(Node):
    def __init__(self, statements):
        self.statements = statements

    def __repr__(self):
        return "\n".join([repr(i) for i in self.statements])

class ArrayConstant(Node):
    def __init__(self, items):
        self.items = items

    def wrap(self, space):
        return space.newlist([item.wrap(space) for item in self.items])

    def execute(self, interp):
        w_list = self.wrap(interp.space)
        return array(interp.space, w_list)

    def __repr__(self):
        return "[" + ", ".join([repr(item) for item in self.items]) + "]"

class SliceConstant(Node):
    def __init__(self, start, stop, step):
        # no negative support for now
        self.start = start
        self.stop = stop
        self.step = step

    def wrap(self, space):
        return SliceObject(self.start, self.stop, self.step)

    def execute(self, interp):
        return SliceObject(self.start, self.stop, self.step)

    def __repr__(self):
        return 'slice(%s,%s,%s)' % (self.start, self.stop, self.step)

class Execute(Node):
    def __init__(self, expr):
        self.expr = expr

    def __repr__(self):
        return repr(self.expr)

    def execute(self, interp):
        interp.results.append(self.expr.execute(interp))

class FunctionCall(Node):
    def __init__(self, name, args):
        self.name = name.strip(" ")
        self.args = args

    def __repr__(self):
        return "%s(%s)" % (self.name, ", ".join([repr(arg)
                                                 for arg in self.args]))

    def execute(self, interp):
        arr = self.args[0].execute(interp)
        if not isinstance(arr, W_NDimArray):
            raise ArgumentNotAnArray
        if self.name in SINGLE_ARG_FUNCTIONS:
            if len(self.args) != 1 and self.name != 'sum':
                raise ArgumentMismatch
            if self.name == "sum":
                if len(self.args)>1:
                    w_res = arr.descr_sum(interp.space,
                                          self.args[1].execute(interp))
                else:
                    w_res = arr.descr_sum(interp.space)
            elif self.name == "prod":
                w_res = arr.descr_prod(interp.space)
            elif self.name == "max":
                w_res = arr.descr_max(interp.space)
            elif self.name == "min":
                w_res = arr.descr_min(interp.space)
            elif self.name == "any":
                w_res = arr.descr_any(interp.space)
            elif self.name == "all":
                w_res = arr.descr_all(interp.space)
            elif self.name == "unegative":
                neg = interp_ufuncs.get(interp.space).negative
                w_res = neg.call(interp.space, [arr])
            elif self.name == "cos":
                cos = interp_ufuncs.get(interp.space).cos
                w_res = cos.call(interp.space, [arr])                
            elif self.name == "flat":
                w_res = arr.descr_get_flatiter(interp.space)
            elif self.name == "tostring":
                arr.descr_tostring(interp.space)
                w_res = None
            else:
                assert False # unreachable code
        elif self.name in TWO_ARG_FUNCTIONS:
            if len(self.args) != 2:
                raise ArgumentMismatch
            arg = self.args[1].execute(interp)
            if not isinstance(arg, W_NDimArray):
                raise ArgumentNotAnArray
            if self.name == "dot":
                w_res = arr.descr_dot(interp.space, arg)
            elif self.name == 'take':
                w_res = arr.descr_take(interp.space, arg)
            else:
                assert False # unreachable code
        elif self.name in THREE_ARG_FUNCTIONS:
            if len(self.args) != 3:
                raise ArgumentMismatch
            arg1 = self.args[1].execute(interp)
            arg2 = self.args[2].execute(interp)
            if not isinstance(arg1, W_NDimArray):
                raise ArgumentNotAnArray
            if not isinstance(arg2, W_NDimArray):
                raise ArgumentNotAnArray
            if self.name == "where":
                w_res = where(interp.space, arr, arg1, arg2)
            else:
                assert False
        else:
            raise WrongFunctionName
        if isinstance(w_res, W_NDimArray):
            return w_res
        if isinstance(w_res, FloatObject):
            dtype = get_dtype_cache(interp.space).w_float64dtype
        elif isinstance(w_res, IntObject):
            dtype = get_dtype_cache(interp.space).w_int64dtype
        elif isinstance(w_res, BoolObject):
            dtype = get_dtype_cache(interp.space).w_booldtype
        elif isinstance(w_res, interp_boxes.W_GenericBox):
            dtype = w_res.get_dtype(interp.space)
        else:
            dtype = None
        return W_NDimArray.new_scalar(interp.space, dtype, w_res)

_REGEXES = [
    ('-?[\d\.]+', 'number'),
    ('\[', 'array_left'),
    (':', 'colon'),
    ('\w+', 'identifier'),
    ('\]', 'array_right'),
    ('(->)|[\+\-\*\/]', 'operator'),
    ('=', 'assign'),
    (',', 'comma'),
    ('\|', 'pipe'),
    ('\(', 'paren_left'),
    ('\)', 'paren_right'),
]
REGEXES = []

for r, name in _REGEXES:
    REGEXES.append((re.compile(r' *(' + r + ')'), name))
del _REGEXES

class Token(object):
    def __init__(self, name, v):
        self.name = name
        self.v = v

    def __repr__(self):
        return '(%s, %s)' % (self.name, self.v)

empty = Token('', '')

class TokenStack(object):
    def __init__(self, tokens):
        self.tokens = tokens
        self.c = 0

    def pop(self):
        token = self.tokens[self.c]
        self.c += 1
        return token

    def get(self, i):
        if self.c + i >= len(self.tokens):
            return empty
        return self.tokens[self.c + i]

    def remaining(self):
        return len(self.tokens) - self.c

    def push(self):
        self.c -= 1

    def __repr__(self):
        return repr(self.tokens[self.c:])

class Parser(object):
    def tokenize(self, line):
        tokens = []
        while True:
            for r, name in REGEXES:
                m = r.match(line)
                if m is not None:
                    g = m.group(0)
                    tokens.append(Token(name, g))
                    line = line[len(g):]
                    if not line:
                        return TokenStack(tokens)
                    break
            else:
                raise TokenizerError(line)

    def parse_number_or_slice(self, tokens):
        start_tok = tokens.pop()
        if start_tok.name == 'colon':
            start = 0
        else:
            if tokens.get(0).name != 'colon':
                return FloatConstant(start_tok.v)
            start = int(start_tok.v)
            tokens.pop()
        if not tokens.get(0).name in ['colon', 'number']:
            stop = -1
            step = 1
        else:
            next = tokens.pop()
            if next.name == 'colon':
                stop = -1
                step = int(tokens.pop().v)
            else:
                stop = int(next.v)
                if tokens.get(0).name == 'colon':
                    tokens.pop()
                    step = int(tokens.pop().v)
                else:
                    step = 1
        return SliceConstant(start, stop, step)


    def parse_expression(self, tokens, accept_comma=False):
        stack = []
        while tokens.remaining():
            token = tokens.pop()
            if token.name == 'identifier':
                if tokens.remaining() and tokens.get(0).name == 'paren_left':
                    stack.append(self.parse_function_call(token.v, tokens))
                else:
                    stack.append(Variable(token.v))
            elif token.name == 'array_left':
                stack.append(ArrayConstant(self.parse_array_const(tokens)))
            elif token.name == 'operator':
                stack.append(Variable(token.v))
            elif token.name == 'number' or token.name == 'colon':
                tokens.push()
                stack.append(self.parse_number_or_slice(tokens))
            elif token.name == 'pipe':
                stack.append(RangeConstant(tokens.pop().v))
                end = tokens.pop()
                assert end.name == 'pipe'
            elif token.name == 'paren_left':
                stack.append(self.parse_complex_constant(tokens))
            elif accept_comma and token.name == 'comma':
                continue
            else:
                tokens.push()
                break
        if accept_comma:
            return stack
        stack.reverse()
        lhs = stack.pop()
        while stack:
            op = stack.pop()
            assert isinstance(op, Variable)
            rhs = stack.pop()
            lhs = Operator(lhs, op.name, rhs)
        return lhs

    def parse_function_call(self, name, tokens):
        args = []
        tokens.pop() # lparen
        while tokens.get(0).name != 'paren_right':
            args += self.parse_expression(tokens, accept_comma=True)
        return FunctionCall(name, args)

    def parse_complex_constant(self, tokens):
        r = tokens.pop()
        assert r.name == 'number'
        assert tokens.pop().name == 'comma'
        i = tokens.pop()
        assert i.name == 'number'
        assert tokens.pop().name == 'paren_right'
        return ComplexConstant(r.v, i.v)

    def parse_array_const(self, tokens):
        elems = []
        while True:
            token = tokens.pop()
            if token.name == 'number':
                elems.append(FloatConstant(token.v))
            elif token.name == 'array_left':
                elems.append(ArrayConstant(self.parse_array_const(tokens)))
            elif token.name == 'paren_left':
                elems.append(self.parse_complex_constant(tokens))
            else:
                raise BadToken()
            token = tokens.pop()
            if token.name == 'array_right':
                return elems
            assert token.name == 'comma'

    def parse_statement(self, tokens):
        if (tokens.get(0).name == 'identifier' and
            tokens.get(1).name == 'assign'):
            lhs = tokens.pop().v
            tokens.pop()
            rhs = self.parse_expression(tokens)
            return Assignment(lhs, rhs)
        elif (tokens.get(0).name == 'identifier' and
              tokens.get(1).name == 'array_left'):
            name = tokens.pop().v
            tokens.pop()
            index = self.parse_expression(tokens)
            tokens.pop()
            tokens.pop()
            return ArrayAssignment(name, index, self.parse_expression(tokens))
        return Execute(self.parse_expression(tokens))

    def parse(self, code):
        statements = []
        for line in code.split("\n"):
            if '#' in line:
                line = line.split('#', 1)[0]
            line = line.strip(" ")
            if line:
                tokens = self.tokenize(line)
                statements.append(self.parse_statement(tokens))
        return Code(statements)

def numpy_compile(code):
    parser = Parser()
    return InterpreterState(parser.parse(code))
