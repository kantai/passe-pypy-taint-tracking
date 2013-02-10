"""Implements the core parts of flow graph creation, in tandem
with rpython.flowspace.objspace.
"""

import sys
import collections

from rpython.tool.error import source_lines
from rpython.tool.stdlib_opcode import host_bytecode_spec
from rpython.flowspace.argument import ArgumentsForTranslation
from rpython.flowspace.model import (Constant, Variable, Block, Link,
    UnwrapException, c_last_exception)
from rpython.flowspace.framestate import (FrameState, recursively_unflatten,
        recursively_flatten)
from rpython.flowspace.specialcase import (rpython_print_item,
        rpython_print_newline)

class FlowingError(Exception):
    """ Signals invalid RPython in the function being analysed"""
    def __init__(self, frame, msg):
        super(FlowingError, self).__init__(msg)
        self.frame = frame

    def __str__(self):
        msg = ['-+' * 30]
        msg += map(str, self.args)
        msg += source_lines(self.frame.graph, None, offset=self.frame.last_instr)
        return "\n".join(msg)

class StopFlowing(Exception):
    pass

class Return(Exception):
    def __init__(self, value):
        self.value = value

class FSException(Exception):
    def __init__(self, w_type, w_value):
        assert w_type is not None
        self.w_type = w_type
        self.w_value = w_value

    def get_w_value(self, _):
        return self.w_value

    def __str__(self):
        return '[%s: %s]' % (self.w_type, self.w_value)

class ImplicitOperationError(FSException):
    pass

class BytecodeCorruption(Exception):
    pass

class SpamBlock(Block):
    # make slots optional, for debugging
    if hasattr(Block, '__slots__'):
        __slots__ = "dead framestate".split()

    def __init__(self, framestate):
        Block.__init__(self, framestate.getvariables())
        self.framestate = framestate
        self.dead = False

class EggBlock(Block):
    # make slots optional, for debugging
    if hasattr(Block, '__slots__'):
        __slots__ = "prevblock booloutcome last_exception".split()

    def __init__(self, inputargs, prevblock, booloutcome):
        Block.__init__(self, inputargs)
        self.prevblock = prevblock
        self.booloutcome = booloutcome

    def extravars(self, last_exception=None, last_exc_value=None):
        self.last_exception = last_exception

def fixeggblocks(graph):
    varnames = graph.func.func_code.co_varnames
    for block in graph.iterblocks():
        if isinstance(block, SpamBlock):
            for name, w_value in zip(varnames, block.framestate.mergeable):
                if isinstance(w_value, Variable):
                    w_value.rename(name)
            del block.framestate     # memory saver

    # EggBlocks reuse the variables of their previous block,
    # which is deemed not acceptable for simplicity of the operations
    # that will be performed later on the flow graph.
    for link in list(graph.iterlinks()):
        block = link.target
        if isinstance(block, EggBlock):
            if (not block.operations and len(block.exits) == 1 and
                link.args == block.inputargs):   # not renamed
                # if the variables are not renamed across this link
                # (common case for EggBlocks) then it's easy enough to
                # get rid of the empty EggBlock.
                link2 = block.exits[0]
                link.args = list(link2.args)
                link.target = link2.target
                assert link2.exitcase is None
            else:
                mapping = {}
                for a in block.inputargs:
                    mapping[a] = Variable(a)
                block.renamevariables(mapping)

# ____________________________________________________________

class Recorder:

    def append(self, operation):
        raise NotImplementedError

    def guessbool(self, frame, w_condition, **kwds):
        raise AssertionError, "cannot guessbool(%s)" % (w_condition,)


class BlockRecorder(Recorder):
    # Records all generated operations into a block.

    def __init__(self, block):
        self.crnt_block = block
        # Final frame state after the operations in the block
        # If this is set, no new space op may be recorded.
        self.final_state = None

    def append(self, operation):
        self.crnt_block.operations.append(operation)

    def guessbool(self, frame, w_condition):
        block = self.crnt_block
        vars = block.getvariables()
        links = []
        for case in [False, True]:
            egg = EggBlock(vars, block, case)
            frame.pendingblocks.append(egg)
            link = Link(vars, egg, case)
            links.append(link)

        block.exitswitch = w_condition
        block.closeblock(*links)
        # forked the graph. Note that False comes before True by default
        # in the exits tuple so that (just in case we need it) we
        # actually have block.exits[False] = elseLink and
        # block.exits[True] = ifLink.
        raise StopFlowing

    def guessexception(self, frame, *cases):
        block = self.crnt_block
        bvars = vars = vars2 = block.getvariables()
        links = []
        for case in [None] + list(cases):
            if case is not None:
                assert block.operations[-1].result is bvars[-1]
                vars = bvars[:-1]
                vars2 = bvars[:-1]
                if case is Exception:
                    last_exc = Variable('last_exception')
                else:
                    last_exc = Constant(case)
                last_exc_value = Variable('last_exc_value')
                vars.extend([last_exc, last_exc_value])
                vars2.extend([Variable(), Variable()])
            egg = EggBlock(vars2, block, case)
            frame.pendingblocks.append(egg)
            link = Link(vars, egg, case)
            if case is not None:
                link.extravars(last_exception=last_exc, last_exc_value=last_exc_value)
                egg.extravars(last_exception=last_exc)
            links.append(link)

        block.exitswitch = c_last_exception
        block.closeblock(*links)
        raise StopFlowing


class Replayer(Recorder):

    def __init__(self, block, booloutcome, nextreplayer):
        self.crnt_block = block
        self.listtoreplay = block.operations
        self.booloutcome = booloutcome
        self.nextreplayer = nextreplayer
        self.index = 0

    def append(self, operation):
        operation.result = self.listtoreplay[self.index].result
        assert operation == self.listtoreplay[self.index], (
            '\n'.join(["Not generating the same operation sequence:"] +
                      [str(s) for s in self.listtoreplay[:self.index]] +
                      ["  ---> | while repeating we see here"] +
                      ["       | %s" % operation] +
                      [str(s) for s in self.listtoreplay[self.index:]]))
        self.index += 1

    def guessbool(self, frame, w_condition, **kwds):
        assert self.index == len(self.listtoreplay)
        frame.recorder = self.nextreplayer
        return self.booloutcome

    def guessexception(self, frame, *classes):
        assert self.index == len(self.listtoreplay)
        frame.recorder = self.nextreplayer
        outcome = self.booloutcome
        if outcome is not None:
            egg = self.nextreplayer.crnt_block
            w_exc_cls, w_exc_value = egg.inputargs[-2:]
            if isinstance(egg.last_exception, Constant):
                w_exc_cls = egg.last_exception
            raise ImplicitOperationError(w_exc_cls, w_exc_value)

# ____________________________________________________________

_unary_ops = [('UNARY_POSITIVE', "pos"),
    ('UNARY_NEGATIVE', "neg"),
    ('UNARY_NOT', "not_"),
    ('UNARY_CONVERT', "repr"),
    ('UNARY_INVERT', "invert"),]

def unaryoperation(OPCODE, op):
    def UNARY_OP(self, *ignored):
        operation = getattr(self.space, op)
        w_1 = self.popvalue()
        w_result = operation(w_1)
        self.pushvalue(w_result)
    UNARY_OP.unaryop = op
    UNARY_OP.func_name = OPCODE
    return UNARY_OP

_binary_ops = [
    ('BINARY_MULTIPLY', "mul"),
    ('BINARY_TRUE_DIVIDE', "truediv"),
    ('BINARY_FLOOR_DIVIDE', "floordiv"),
    ('BINARY_DIVIDE', "div"),
    ('BINARY_MODULO', "mod"),
    ('BINARY_ADD', "add"),
    ('BINARY_SUBTRACT', "sub"),
    ('BINARY_SUBSCR', "getitem"),
    ('BINARY_LSHIFT', "lshift"),
    ('BINARY_RSHIFT', "rshift"),
    ('BINARY_AND', "and_"),
    ('BINARY_XOR', "xor"),
    ('BINARY_OR', "or_"),
    ('INPLACE_MULTIPLY', "inplace_mul"),
    ('INPLACE_TRUE_DIVIDE', "inplace_truediv"),
    ('INPLACE_FLOOR_DIVIDE', "inplace_floordiv"),
    ('INPLACE_DIVIDE', "inplace_div"),
    ('INPLACE_MODULO', "inplace_mod"),
    ('INPLACE_ADD', "inplace_add"),
    ('INPLACE_SUBTRACT', "inplace_sub"),
    ('INPLACE_LSHIFT', "inplace_lshift"),
    ('INPLACE_RSHIFT', "inplace_rshift"),
    ('INPLACE_AND', "inplace_and"),
    ('INPLACE_XOR', "inplace_xor"),
    ('INPLACE_OR', "inplace_or"),
]

def binaryoperation(OPCODE, op):
    """NOT_RPYTHON"""
    def BINARY_OP(self, *ignored):
        operation = getattr(self.space, op)
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        w_result = operation(w_1, w_2)
        self.pushvalue(w_result)
    BINARY_OP.binop = op
    BINARY_OP.func_name = OPCODE
    return BINARY_OP

_unsupported_ops = [
    ('BINARY_POWER', "a ** b"),
    ('BUILD_CLASS', 'creating new classes'),
    ('EXEC_STMT', 'exec statement'),
    ('STOP_CODE', '???'),
    ('STORE_NAME', 'modifying globals'),
    ('INPLACE_POWER', 'a **= b'),
    ('LOAD_LOCALS', 'locals()'),
    ('IMPORT_STAR', 'import *'),
    ('MISSING_OPCODE', '???'),
    ('DELETE_GLOBAL', 'modifying globals'),
    ('DELETE_NAME', 'modifying globals'),
    ('DELETE_ATTR', 'deleting attributes'),
]

def unsupportedoperation(OPCODE, msg):
    def UNSUPPORTED(self, *ignored):
        raise FlowingError(self, "%s is not RPython" % (msg,))
    UNSUPPORTED.func_name = OPCODE
    return UNSUPPORTED

compare_method = [
    "cmp_lt",   # "<"
    "cmp_le",   # "<="
    "cmp_eq",   # "=="
    "cmp_ne",   # "!="
    "cmp_gt",   # ">"
    "cmp_ge",   # ">="
    "cmp_in",
    "cmp_not_in",
    "cmp_is",
    "cmp_is_not",
    "cmp_exc_match",
    ]

class FlowSpaceFrame(object):
    opcode_method_names = host_bytecode_spec.method_names

    def __init__(self, space, graph, code):
        self.graph = graph
        func = graph.func
        self.pycode = code
        self.space = space
        self.w_globals = Constant(func.func_globals)
        self.blockstack = []

        self.init_closure(func.func_closure)
        self.f_lineno = code.co_firstlineno
        self.last_instr = 0

        self.init_locals_stack(code)
        self.w_locals = None # XXX: only for compatibility with PyFrame

        self.joinpoints = {}

    def init_closure(self, closure):
        if closure is None:
            self.closure = []
        else:
            self.closure = [self.space.wrap(c.cell_contents) for c in closure]
        assert len(self.closure) == len(self.pycode.co_freevars)

    def init_locals_stack(self, code):
        """
        Initialize the locals and the stack.

        The locals are ordered according to self.pycode.signature.
        """
        self.valuestackdepth = code.co_nlocals
        self.locals_stack_w = [None] * (code.co_stacksize + code.co_nlocals)

    def pushvalue(self, w_object):
        depth = self.valuestackdepth
        self.locals_stack_w[depth] = w_object
        self.valuestackdepth = depth + 1

    def popvalue(self):
        depth = self.valuestackdepth - 1
        assert depth >= self.pycode.co_nlocals, "pop from empty value stack"
        w_object = self.locals_stack_w[depth]
        self.locals_stack_w[depth] = None
        self.valuestackdepth = depth
        return w_object

    def peekvalue(self, index_from_top=0):
        # NOTE: top of the stack is peekvalue(0).
        index = self.valuestackdepth + ~index_from_top
        assert index >= self.pycode.co_nlocals, (
            "peek past the bottom of the stack")
        return self.locals_stack_w[index]

    def pushrevvalues(self, n, values_w): # n should be len(values_w)
        assert len(values_w) == n
        for i in range(n - 1, -1, -1):
            self.pushvalue(values_w[i])

    def settopvalue(self, w_object, index_from_top=0):
        index = self.valuestackdepth + ~index_from_top
        assert index >= self.pycode.co_nlocals, (
            "settop past the bottom of the stack")
        self.locals_stack_w[index] = w_object

    def popvalues(self, n):
        values_w = [self.popvalue() for i in range(n)]
        values_w.reverse()
        return values_w

    def peekvalues(self, n):
        values_w = [None] * n
        base = self.valuestackdepth - n
        while True:
            n -= 1
            if n < 0:
                break
            values_w[n] = self.locals_stack_w[base+n]
        return values_w

    def dropvalues(self, n):
        finaldepth = self.valuestackdepth - n
        for n in range(finaldepth, self.valuestackdepth):
            self.locals_stack_w[n] = None
        self.valuestackdepth = finaldepth

    def dropvaluesuntil(self, finaldepth):
        for n in range(finaldepth, self.valuestackdepth):
            self.locals_stack_w[n] = None
        self.valuestackdepth = finaldepth

    def save_locals_stack(self):
        return self.locals_stack_w[:self.valuestackdepth]

    def restore_locals_stack(self, items_w):
        self.locals_stack_w[:len(items_w)] = items_w
        self.dropvaluesuntil(len(items_w))

    def unrollstack(self, unroller_kind):
        while self.blockstack:
            block = self.blockstack.pop()
            if (block.handling_mask & unroller_kind) != 0:
                return block
            block.cleanupstack(self)
        return None

    def unrollstack_and_jump(self, unroller):
        block = self.unrollstack(unroller.kind)
        if block is None:
            raise BytecodeCorruption("misplaced bytecode - should not return")
        return block.handle(self, unroller)

    def getstate(self):
        # getfastscope() can return real None, for undefined locals
        data = self.save_locals_stack()
        if self.last_exception is None:
            data.append(Constant(None))
            data.append(Constant(None))
        else:
            data.append(self.last_exception.w_type)
            data.append(self.last_exception.w_value)
        recursively_flatten(self.space, data)
        return FrameState(data, self.blockstack[:], self.last_instr)

    def setstate(self, state):
        """ Reset the frame to the given state. """
        data = state.mergeable[:]
        recursively_unflatten(self.space, data)
        self.restore_locals_stack(data[:-2])  # Nones == undefined locals
        if data[-2] == Constant(None):
            assert data[-1] == Constant(None)
            self.last_exception = None
        else:
            self.last_exception = FSException(data[-2], data[-1])
        self.last_instr = state.next_instr
        self.blockstack = state.blocklist[:]

    def recording(self, block):
        """ Setup recording of the block and return the recorder. """
        parentblocks = []
        parent = block
        while isinstance(parent, EggBlock):
            parent = parent.prevblock
            parentblocks.append(parent)
        # parentblocks = [Egg, Egg, ..., Egg, Spam] not including block
        if parent.dead:
            raise StopFlowing
        self.setstate(parent.framestate)
        recorder = BlockRecorder(block)
        prevblock = block
        for parent in parentblocks:
            recorder = Replayer(parent, prevblock.booloutcome, recorder)
            prevblock = parent
        return recorder

    def record(self, spaceop):
        """Record an operation into the active block"""
        recorder = self.recorder
        if getattr(recorder, 'final_state', None) is not None:
            self.mergeblock(recorder.crnt_block, recorder.final_state)
            raise StopFlowing
        recorder.append(spaceop)

    def guessbool(self, w_condition, **kwds):
        return self.recorder.guessbool(self, w_condition, **kwds)

    def handle_implicit_exceptions(self, exceptions):
        """
        Catch possible exceptions implicitly.

        If the FSException is not caught in the same function, it will
        produce an exception-raising return block in the flow graph. Note that
        even if the interpreter re-raises the exception, it will not be the
        same ImplicitOperationError instance internally.
        """
        if not exceptions:
            return
        return self.recorder.guessexception(self, *exceptions)

    def build_flow(self):
        graph = self.graph
        self.pendingblocks = collections.deque([graph.startblock])
        while self.pendingblocks:
            block = self.pendingblocks.popleft()
            try:
                self.recorder = self.recording(block)
                while True:
                    self.last_instr = self.handle_bytecode(self.last_instr)
                    self.recorder.final_state = self.getstate()

            except ImplicitOperationError, e:
                if isinstance(e.w_type, Constant):
                    exc_cls = e.w_type.value
                else:
                    exc_cls = Exception
                msg = "implicit %s shouldn't occur" % exc_cls.__name__
                w_type = Constant(AssertionError)
                w_value = Constant(AssertionError(msg))
                link = Link([w_type, w_value], graph.exceptblock)
                self.recorder.crnt_block.closeblock(link)

            except FSException, e:
                if e.w_type is self.space.w_ImportError:
                    msg = 'import statement always raises %s' % e
                    raise ImportError(msg)
                link = Link([e.w_type, e.w_value], graph.exceptblock)
                self.recorder.crnt_block.closeblock(link)

            except StopFlowing:
                pass

            except Return as exc:
                w_result = exc.value
                link = Link([w_result], graph.returnblock)
                self.recorder.crnt_block.closeblock(link)

        del self.recorder

    def mergeblock(self, currentblock, currentstate):
        next_instr = currentstate.next_instr
        # can 'currentstate' be merged with one of the blocks that
        # already exist for this bytecode position?
        candidates = self.joinpoints.setdefault(next_instr, [])
        for block in candidates:
            newstate = block.framestate.union(currentstate)
            if newstate is None:
                continue
            elif newstate == block.framestate:
                outputargs = currentstate.getoutputargs(newstate)
                currentblock.closeblock(Link(outputargs, block))
                return
            else:
                break
        else:
            newstate = currentstate.copy()
            block = None

        newblock = SpamBlock(newstate)
        # unconditionally link the current block to the newblock
        outputargs = currentstate.getoutputargs(newstate)
        link = Link(outputargs, newblock)
        currentblock.closeblock(link)

        if block is not None:
            # to simplify the graph, we patch the old block to point
            # directly at the new block which is its generalization
            block.dead = True
            block.operations = ()
            block.exitswitch = None
            outputargs = block.framestate.getoutputargs(newstate)
            block.recloseblock(Link(outputargs, newblock))
            candidates.remove(block)
        candidates.insert(0, newblock)
        self.pendingblocks.append(newblock)

    # hack for unrolling iterables, don't use this
    def replace_in_stack(self, oldvalue, newvalue):
        w_new = Constant(newvalue)
        stack_items_w = self.locals_stack_w
        for i in range(self.valuestackdepth-1, self.pycode.co_nlocals-1, -1):
            w_v = stack_items_w[i]
            if isinstance(w_v, Constant):
                if w_v.value is oldvalue:
                    # replace the topmost item of the stack that is equal
                    # to 'oldvalue' with 'newvalue'.
                    stack_items_w[i] = w_new
                    break

    def handle_bytecode(self, next_instr):
        next_instr, methodname, oparg = self.pycode.read(next_instr)
        try:
            res = getattr(self, methodname)(oparg, next_instr)
            return res if res is not None else next_instr
        except FSException, operr:
            return self.handle_operation_error(operr)

    def handle_operation_error(self, operr):
        block = self.unrollstack(SApplicationException.kind)
        if block is None:
            raise operr
        else:
            unroller = SApplicationException(operr)
            next_instr = block.handle(self, unroller)
            return next_instr

    def getlocalvarname(self, index):
        return self.pycode.co_varnames[index]

    def getconstant_w(self, index):
        return self.space.wrap(self.pycode.consts[index])

    def getname_u(self, index):
        return self.pycode.names[index]

    def getname_w(self, index):
        return Constant(self.pycode.names[index])

    def BAD_OPCODE(self, _, next_instr):
        raise FlowingError(self, "This operation is not RPython")

    def BREAK_LOOP(self, oparg, next_instr):
        return self.unrollstack_and_jump(SBreakLoop.singleton)

    def CONTINUE_LOOP(self, startofloop, next_instr):
        unroller = SContinueLoop(startofloop)
        return self.unrollstack_and_jump(unroller)

    def cmp_lt(self, w_1, w_2):
        return self.space.lt(w_1, w_2)

    def cmp_le(self, w_1, w_2):
        return self.space.le(w_1, w_2)

    def cmp_eq(self, w_1, w_2):
        return self.space.eq(w_1, w_2)

    def cmp_ne(self, w_1, w_2):
        return self.space.ne(w_1, w_2)

    def cmp_gt(self, w_1, w_2):
        return self.space.gt(w_1, w_2)

    def cmp_ge(self, w_1, w_2):
        return self.space.ge(w_1, w_2)

    def cmp_in(self, w_1, w_2):
        return self.space.contains(w_2, w_1)

    def cmp_not_in(self, w_1, w_2):
        return self.space.not_(self.space.contains(w_2, w_1))

    def cmp_is(self, w_1, w_2):
        return self.space.is_(w_1, w_2)

    def cmp_is_not(self, w_1, w_2):
        return self.space.not_(self.space.is_(w_1, w_2))

    def cmp_exc_match(self, w_1, w_2):
        return self.space.newbool(self.space.exception_match(w_1, w_2))

    def COMPARE_OP(self, testnum, next_instr):
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        w_result = getattr(self, compare_method[testnum])(w_1, w_2)
        self.pushvalue(w_result)

    def RAISE_VARARGS(self, nbargs, next_instr):
        space = self.space
        if nbargs == 0:
            if self.last_exception is not None:
                operr = self.last_exception
                if isinstance(operr, ImplicitOperationError):
                    # re-raising an implicit operation makes it an explicit one
                    operr = FSException(operr.w_type, operr.w_value)
                self.last_exception = operr
                raise operr
            else:
                raise FSException(space.w_TypeError,
                    space.wrap("raise: no active exception to re-raise"))

        w_value = w_traceback = space.w_None
        if nbargs >= 3:
            w_traceback = self.popvalue()
        if nbargs >= 2:
            w_value = self.popvalue()
        if 1:
            w_type = self.popvalue()
        operror = space.exc_from_raise(w_type, w_value)
        raise operror

    def IMPORT_NAME(self, nameindex, next_instr):
        space = self.space
        modulename = self.getname_u(nameindex)
        glob = space.unwrap(self.w_globals)
        fromlist = space.unwrap(self.popvalue())
        level = self.popvalue().value
        w_obj = space.import_name(modulename, glob, None, fromlist, level)
        self.pushvalue(w_obj)

    def IMPORT_FROM(self, nameindex, next_instr):
        w_name = self.getname_w(nameindex)
        w_module = self.peekvalue()
        self.pushvalue(self.space.import_from(w_module, w_name))

    def RETURN_VALUE(self, oparg, next_instr):
        w_returnvalue = self.popvalue()
        block = self.unrollstack(SReturnValue.kind)
        if block is None:
            raise Return(w_returnvalue)
        else:
            unroller = SReturnValue(w_returnvalue)
            next_instr = block.handle(self, unroller)
            return next_instr    # now inside a 'finally' block

    def END_FINALLY(self, oparg, next_instr):
        # unlike CPython, there are two statically distinct cases: the
        # END_FINALLY might be closing an 'except' block or a 'finally'
        # block.  In the first case, the stack contains three items:
        #   [exception type we are now handling]
        #   [exception value we are now handling]
        #   [wrapped SApplicationException]
        # In the case of a finally: block, the stack contains only one
        # item (unlike CPython which can have 1, 2 or 3 items):
        #   [wrapped subclass of SuspendedUnroller]
        w_top = self.popvalue()
        if w_top == self.space.w_None:
            # finally: block with no unroller active
            return
        elif isinstance(w_top, SuspendedUnroller):
            # case of a finally: block
            return self.unroll_finally(w_top)
        else:
            # case of an except: block.  We popped the exception type
            self.popvalue()        #     Now we pop the exception value
            unroller = self.popvalue()
            return self.unroll_finally(unroller)

    def unroll_finally(self, unroller):
        # go on unrolling the stack
        block = self.unrollstack(unroller.kind)
        if block is None:
            unroller.nomoreblocks()
        else:
            return block.handle(self, unroller)

    def POP_BLOCK(self, oparg, next_instr):
        block = self.blockstack.pop()
        block.cleanupstack(self)  # the block knows how to clean up the value stack

    def JUMP_ABSOLUTE(self, jumpto, next_instr):
        return jumpto

    def YIELD_VALUE(self, _, next_instr):
        assert self.pycode.is_generator
        w_result = self.popvalue()
        self.space.do_operation('yield', w_result)
        # XXX yield expressions not supported. This will blow up if the value
        # isn't popped straightaway.
        self.pushvalue(None)

    PRINT_EXPR = BAD_OPCODE
    PRINT_ITEM_TO = BAD_OPCODE
    PRINT_NEWLINE_TO = BAD_OPCODE

    def PRINT_ITEM(self, oparg, next_instr):
        w_item = self.popvalue()
        w_s = self.space.do_operation('str', w_item)
        self.space.appcall(rpython_print_item, w_s)

    def PRINT_NEWLINE(self, oparg, next_instr):
        self.space.appcall(rpython_print_newline)

    def JUMP_FORWARD(self, jumpby, next_instr):
        next_instr += jumpby
        return next_instr

    def JUMP_IF_FALSE(self, stepby, next_instr):
        # Python <= 2.6 only
        w_cond = self.peekvalue()
        if not self.space.is_true(w_cond):
            next_instr += stepby
        return next_instr

    def JUMP_IF_TRUE(self, stepby, next_instr):
        # Python <= 2.6 only
        w_cond = self.peekvalue()
        if self.space.is_true(w_cond):
            next_instr += stepby
        return next_instr

    def POP_JUMP_IF_FALSE(self, target, next_instr):
        w_value = self.popvalue()
        if not self.space.is_true(w_value):
            return target
        return next_instr

    def POP_JUMP_IF_TRUE(self, target, next_instr):
        w_value = self.popvalue()
        if self.space.is_true(w_value):
            return target
        return next_instr

    def JUMP_IF_FALSE_OR_POP(self, target, next_instr):
        w_value = self.peekvalue()
        if not self.space.is_true(w_value):
            return target
        self.popvalue()
        return next_instr

    def JUMP_IF_TRUE_OR_POP(self, target, next_instr):
        w_value = self.peekvalue()
        if self.space.is_true(w_value):
            return target
        self.popvalue()
        return next_instr

    def GET_ITER(self, oparg, next_instr):
        w_iterable = self.popvalue()
        w_iterator = self.space.iter(w_iterable)
        self.pushvalue(w_iterator)

    def FOR_ITER(self, jumpby, next_instr):
        w_iterator = self.peekvalue()
        try:
            w_nextitem = self.space.next(w_iterator)
        except FSException, e:
            if not self.space.exception_match(e.w_type, self.space.w_StopIteration):
                raise
            # iterator exhausted
            self.popvalue()
            next_instr += jumpby
        else:
            self.pushvalue(w_nextitem)
        return next_instr

    def SETUP_LOOP(self, offsettoend, next_instr):
        block = LoopBlock(self, next_instr + offsettoend)
        self.blockstack.append(block)

    def SETUP_EXCEPT(self, offsettoend, next_instr):
        block = ExceptBlock(self, next_instr + offsettoend)
        self.blockstack.append(block)

    def SETUP_FINALLY(self, offsettoend, next_instr):
        block = FinallyBlock(self, next_instr + offsettoend)
        self.blockstack.append(block)

    def SETUP_WITH(self, offsettoend, next_instr):
        # A simpler version than the 'real' 2.7 one:
        # directly call manager.__enter__(), don't use special lookup functions
        # which don't make sense on the RPython type system.
        w_manager = self.peekvalue()
        w_exit = self.space.getattr(w_manager, self.space.wrap("__exit__"))
        self.settopvalue(w_exit)
        w_result = self.space.call_method(w_manager, "__enter__")
        block = WithBlock(self, next_instr + offsettoend)
        self.blockstack.append(block)
        self.pushvalue(w_result)

    def WITH_CLEANUP(self, oparg, next_instr):
        # Note: RPython context managers receive None in lieu of tracebacks
        # and cannot suppress the exception.
        # This opcode changed a lot between CPython versions
        if sys.version_info >= (2, 6):
            unroller = self.popvalue()
            w_exitfunc = self.popvalue()
            self.pushvalue(unroller)
        else:
            w_exitfunc = self.popvalue()
            unroller = self.peekvalue(0)

        w_None = self.space.w_None
        if isinstance(unroller, SApplicationException):
            operr = unroller.operr
            # The annotator won't allow to merge exception types with None.
            # Replace it with the exception value...
            self.space.call_function(w_exitfunc,
                    operr.w_value, operr.w_value, w_None)
        else:
            self.space.call_function(w_exitfunc, w_None, w_None, w_None)

    def LOAD_FAST(self, varindex, next_instr):
        w_value = self.locals_stack_w[varindex]
        if w_value is None:
            raise FlowingError(self, "Local variable referenced before assignment")
        self.pushvalue(w_value)

    def LOAD_CONST(self, constindex, next_instr):
        w_const = self.getconstant_w(constindex)
        self.pushvalue(w_const)

    def LOAD_GLOBAL(self, nameindex, next_instr):
        w_result = self.space.find_global(self.w_globals, self.getname_u(nameindex))
        self.pushvalue(w_result)
    LOAD_NAME = LOAD_GLOBAL

    def LOAD_ATTR(self, nameindex, next_instr):
        "obj.attributename"
        w_obj = self.popvalue()
        w_attributename = self.getname_w(nameindex)
        w_value = self.space.getattr(w_obj, w_attributename)
        self.pushvalue(w_value)
    LOOKUP_METHOD = LOAD_ATTR

    def LOAD_DEREF(self, varindex, next_instr):
        self.pushvalue(self.closure[varindex])

    def STORE_FAST(self, varindex, next_instr):
        w_newvalue = self.popvalue()
        assert w_newvalue is not None
        self.locals_stack_w[varindex] = w_newvalue

    def STORE_GLOBAL(self, nameindex, next_instr):
        varname = self.getname_u(nameindex)
        raise FlowingError(self,
                "Attempting to modify global variable  %r." % (varname))

    def POP_TOP(self, oparg, next_instr):
        self.popvalue()

    def ROT_TWO(self, oparg, next_instr):
        w_1 = self.popvalue()
        w_2 = self.popvalue()
        self.pushvalue(w_1)
        self.pushvalue(w_2)

    def ROT_THREE(self, oparg, next_instr):
        w_1 = self.popvalue()
        w_2 = self.popvalue()
        w_3 = self.popvalue()
        self.pushvalue(w_1)
        self.pushvalue(w_3)
        self.pushvalue(w_2)

    def ROT_FOUR(self, oparg, next_instr):
        w_1 = self.popvalue()
        w_2 = self.popvalue()
        w_3 = self.popvalue()
        w_4 = self.popvalue()
        self.pushvalue(w_1)
        self.pushvalue(w_4)
        self.pushvalue(w_3)
        self.pushvalue(w_2)

    def DUP_TOP(self, oparg, next_instr):
        w_1 = self.peekvalue()
        self.pushvalue(w_1)

    def DUP_TOPX(self, itemcount, next_instr):
        delta = itemcount - 1
        while True:
            itemcount -= 1
            if itemcount < 0:
                break
            w_value = self.peekvalue(delta)
            self.pushvalue(w_value)

    for OPCODE, op in _unary_ops:
        locals()[OPCODE] = unaryoperation(OPCODE, op)

    for OPCODE, op in _binary_ops:
        locals()[OPCODE] = binaryoperation(OPCODE, op)

    for OPCODE, op in _unsupported_ops:
        locals()[OPCODE] = unsupportedoperation(OPCODE, op)

    def BUILD_LIST_FROM_ARG(self, _, next_instr):
        # This opcode was added with pypy-1.8.  Here is a simpler
        # version, enough for annotation.
        last_val = self.popvalue()
        self.pushvalue(self.space.newlist([]))
        self.pushvalue(last_val)

    def call_function(self, oparg, w_star=None, w_starstar=None):
        n_arguments = oparg & 0xff
        n_keywords = (oparg>>8) & 0xff
        if n_keywords:
            keywords = [None] * n_keywords
            keywords_w = [None] * n_keywords
            while True:
                n_keywords -= 1
                if n_keywords < 0:
                    break
                w_value = self.popvalue()
                w_key = self.popvalue()
                key = self.space.str_w(w_key)
                keywords[n_keywords] = key
                keywords_w[n_keywords] = w_value
        else:
            keywords = None
            keywords_w = None
        arguments = self.popvalues(n_arguments)
        args = ArgumentsForTranslation(self.space, arguments, keywords,
                keywords_w, w_star, w_starstar)
        w_function  = self.popvalue()
        w_result = self.space.call_args(w_function, args)
        self.pushvalue(w_result)

    def CALL_FUNCTION(self, oparg, next_instr):
        self.call_function(oparg)
    CALL_METHOD = CALL_FUNCTION

    def CALL_FUNCTION_VAR(self, oparg, next_instr):
        w_varargs = self.popvalue()
        self.call_function(oparg, w_varargs)

    def CALL_FUNCTION_KW(self, oparg, next_instr):
        w_varkw = self.popvalue()
        self.call_function(oparg, None, w_varkw)

    def CALL_FUNCTION_VAR_KW(self, oparg, next_instr):
        w_varkw = self.popvalue()
        w_varargs = self.popvalue()
        self.call_function(oparg, w_varargs, w_varkw)

    def MAKE_FUNCTION(self, numdefaults, next_instr):
        w_codeobj = self.popvalue()
        defaults = self.popvalues(numdefaults)
        fn = self.space.newfunction(w_codeobj, self.w_globals, defaults)
        self.pushvalue(fn)

    def STORE_ATTR(self, nameindex, next_instr):
        "obj.attributename = newvalue"
        w_attributename = self.getname_w(nameindex)
        w_obj = self.popvalue()
        w_newvalue = self.popvalue()
        self.space.setattr(w_obj, w_attributename, w_newvalue)

    def UNPACK_SEQUENCE(self, itemcount, next_instr):
        w_iterable = self.popvalue()
        items = self.space.unpackiterable(w_iterable, itemcount)
        self.pushrevvalues(itemcount, items)

    def slice(self, w_start, w_end):
        w_obj = self.popvalue()
        w_result = self.space.getslice(w_obj, w_start, w_end)
        self.pushvalue(w_result)

    def SLICE_0(self, oparg, next_instr):
        self.slice(self.space.w_None, self.space.w_None)

    def SLICE_1(self, oparg, next_instr):
        w_start = self.popvalue()
        self.slice(w_start, self.space.w_None)

    def SLICE_2(self, oparg, next_instr):
        w_end = self.popvalue()
        self.slice(self.space.w_None, w_end)

    def SLICE_3(self, oparg, next_instr):
        w_end = self.popvalue()
        w_start = self.popvalue()
        self.slice(w_start, w_end)

    def storeslice(self, w_start, w_end):
        w_obj = self.popvalue()
        w_newvalue = self.popvalue()
        self.space.setslice(w_obj, w_start, w_end, w_newvalue)

    def STORE_SLICE_0(self, oparg, next_instr):
        self.storeslice(self.space.w_None, self.space.w_None)

    def STORE_SLICE_1(self, oparg, next_instr):
        w_start = self.popvalue()
        self.storeslice(w_start, self.space.w_None)

    def STORE_SLICE_2(self, oparg, next_instr):
        w_end = self.popvalue()
        self.storeslice(self.space.w_None, w_end)

    def STORE_SLICE_3(self, oparg, next_instr):
        w_end = self.popvalue()
        w_start = self.popvalue()
        self.storeslice(w_start, w_end)

    def deleteslice(self, w_start, w_end):
        w_obj = self.popvalue()
        self.space.delslice(w_obj, w_start, w_end)

    def DELETE_SLICE_0(self, oparg, next_instr):
        self.deleteslice(self.space.w_None, self.space.w_None)

    def DELETE_SLICE_1(self, oparg, next_instr):
        w_start = self.popvalue()
        self.deleteslice(w_start, self.space.w_None)

    def DELETE_SLICE_2(self, oparg, next_instr):
        w_end = self.popvalue()
        self.deleteslice(self.space.w_None, w_end)

    def DELETE_SLICE_3(self, oparg, next_instr):
        w_end = self.popvalue()
        w_start = self.popvalue()
        self.deleteslice(w_start, w_end)

    def LIST_APPEND(self, oparg, next_instr):
        w = self.popvalue()
        if sys.version_info < (2, 7):
            v = self.popvalue()
        else:
            v = self.peekvalue(oparg - 1)
        self.space.call_method(v, 'append', w)

    def DELETE_FAST(self, varindex, next_instr):
        if self.locals_stack_w[varindex] is None:
            varname = self.getlocalvarname(varindex)
            message = "local variable '%s' referenced before assignment"
            raise UnboundLocalError(message, varname)
        self.locals_stack_w[varindex] = None

    def STORE_MAP(self, oparg, next_instr):
        w_key = self.popvalue()
        w_value = self.popvalue()
        w_dict = self.peekvalue()
        self.space.setitem(w_dict, w_key, w_value)

    def STORE_SUBSCR(self, oparg, next_instr):
        "obj[subscr] = newvalue"
        w_subscr = self.popvalue()
        w_obj = self.popvalue()
        w_newvalue = self.popvalue()
        self.space.setitem(w_obj, w_subscr, w_newvalue)

    def BUILD_SLICE(self, numargs, next_instr):
        if numargs == 3:
            w_step = self.popvalue()
        elif numargs == 2:
            w_step = self.space.w_None
        else:
            raise BytecodeCorruption
        w_end = self.popvalue()
        w_start = self.popvalue()
        w_slice = self.space.newslice(w_start, w_end, w_step)
        self.pushvalue(w_slice)

    def DELETE_SUBSCR(self, oparg, next_instr):
        "del obj[subscr]"
        w_subscr = self.popvalue()
        w_obj = self.popvalue()
        self.space.delitem(w_obj, w_subscr)

    def BUILD_TUPLE(self, itemcount, next_instr):
        items = self.popvalues(itemcount)
        w_tuple = self.space.newtuple(items)
        self.pushvalue(w_tuple)

    def BUILD_LIST(self, itemcount, next_instr):
        items = self.popvalues(itemcount)
        w_list = self.space.newlist(items)
        self.pushvalue(w_list)

    def BUILD_MAP(self, itemcount, next_instr):
        w_dict = self.space.newdict()
        self.pushvalue(w_dict)

    def NOP(self, *args):
        pass

    # XXX Unimplemented 2.7 opcodes ----------------

    # Set literals, set comprehensions

    def BUILD_SET(self, oparg, next_instr):
        raise NotImplementedError("BUILD_SET")

    def SET_ADD(self, oparg, next_instr):
        raise NotImplementedError("SET_ADD")

    # Dict comprehensions

    def MAP_ADD(self, oparg, next_instr):
        raise NotImplementedError("MAP_ADD")

    # Closures

    STORE_DEREF = BAD_OPCODE
    LOAD_CLOSURE = BAD_OPCODE
    MAKE_CLOSURE = BAD_OPCODE

### Frame blocks ###

class SuspendedUnroller(object):
    """Abstract base class for interpreter-level objects that
    instruct the interpreter to change the control flow and the
    block stack.

    The concrete subclasses correspond to the various values WHY_XXX
    values of the why_code enumeration in ceval.c:

                WHY_NOT,        OK, not this one :-)
                WHY_EXCEPTION,  SApplicationException
                WHY_RERAISE,    implemented differently, see Reraise
                WHY_RETURN,     SReturnValue
                WHY_BREAK,      SBreakLoop
                WHY_CONTINUE,   SContinueLoop
                WHY_YIELD       not needed
    """
    def nomoreblocks(self):
        raise BytecodeCorruption("misplaced bytecode - should not return")

    # NB. for the flow object space, the state_(un)pack_variables methods
    # give a way to "pickle" and "unpickle" the SuspendedUnroller by
    # enumerating the Variables it contains.

class SReturnValue(SuspendedUnroller):
    """Signals a 'return' statement.
    Argument is the wrapped object to return."""
    kind = 0x01
    def __init__(self, w_returnvalue):
        self.w_returnvalue = w_returnvalue

    def nomoreblocks(self):
        raise Return(self.w_returnvalue)

    def state_unpack_variables(self, space):
        return [self.w_returnvalue]

    @staticmethod
    def state_pack_variables(space, w_returnvalue):
        return SReturnValue(w_returnvalue)

class SApplicationException(SuspendedUnroller):
    """Signals an application-level exception
    (i.e. an OperationException)."""
    kind = 0x02
    def __init__(self, operr):
        self.operr = operr

    def nomoreblocks(self):
        raise self.operr

    def state_unpack_variables(self, space):
        return [self.operr.w_type, self.operr.w_value]

    @staticmethod
    def state_pack_variables(space, w_type, w_value):
        return SApplicationException(FSException(w_type, w_value))

class SBreakLoop(SuspendedUnroller):
    """Signals a 'break' statement."""
    kind = 0x04

    def state_unpack_variables(self, space):
        return []

    @staticmethod
    def state_pack_variables(space):
        return SBreakLoop.singleton

SBreakLoop.singleton = SBreakLoop()

class SContinueLoop(SuspendedUnroller):
    """Signals a 'continue' statement.
    Argument is the bytecode position of the beginning of the loop."""
    kind = 0x08
    def __init__(self, jump_to):
        self.jump_to = jump_to

    def state_unpack_variables(self, space):
        return [space.wrap(self.jump_to)]

    @staticmethod
    def state_pack_variables(space, w_jump_to):
        return SContinueLoop(space.int_w(w_jump_to))


class FrameBlock(object):
    """Abstract base class for frame blocks from the blockstack,
    used by the SETUP_XXX and POP_BLOCK opcodes."""

    def __init__(self, frame, handlerposition):
        self.handlerposition = handlerposition
        self.valuestackdepth = frame.valuestackdepth

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.handlerposition == other.handlerposition and
                self.valuestackdepth == other.valuestackdepth)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash((self.handlerposition, self.valuestackdepth))

    def cleanupstack(self, frame):
        frame.dropvaluesuntil(self.valuestackdepth)

    def handle(self, frame, unroller):
        raise NotImplementedError

class LoopBlock(FrameBlock):
    """A loop block.  Stores the end-of-loop pointer in case of 'break'."""

    _opname = 'SETUP_LOOP'
    handling_mask = SBreakLoop.kind | SContinueLoop.kind

    def handle(self, frame, unroller):
        if isinstance(unroller, SContinueLoop):
            # re-push the loop block without cleaning up the value stack,
            # and jump to the beginning of the loop, stored in the
            # exception's argument
            frame.blockstack.append(self)
            return unroller.jump_to
        else:
            # jump to the end of the loop
            self.cleanupstack(frame)
            return self.handlerposition

class ExceptBlock(FrameBlock):
    """An try:except: block.  Stores the position of the exception handler."""

    _opname = 'SETUP_EXCEPT'
    handling_mask = SApplicationException.kind

    def handle(self, frame, unroller):
        # push the exception to the value stack for inspection by the
        # exception handler (the code after the except:)
        self.cleanupstack(frame)
        assert isinstance(unroller, SApplicationException)
        operationerr = unroller.operr
        # the stack setup is slightly different than in CPython:
        # instead of the traceback, we store the unroller object,
        # wrapped.
        frame.pushvalue(unroller)
        frame.pushvalue(operationerr.get_w_value(frame.space))
        frame.pushvalue(operationerr.w_type)
        frame.last_exception = operationerr
        return self.handlerposition   # jump to the handler

class FinallyBlock(FrameBlock):
    """A try:finally: block.  Stores the position of the exception handler."""

    _opname = 'SETUP_FINALLY'
    handling_mask = -1     # handles every kind of SuspendedUnroller

    def handle(self, frame, unroller):
        # any abnormal reason for unrolling a finally: triggers the end of
        # the block unrolling and the entering the finally: handler.
        self.cleanupstack(frame)
        frame.pushvalue(unroller)
        return self.handlerposition   # jump to the handler


class WithBlock(FinallyBlock):

    def handle(self, frame, unroller):
        return FinallyBlock.handle(self, frame, unroller)
