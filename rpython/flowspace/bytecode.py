"""
Bytecode handling classes and functions for use by the flow space.
"""
from rpython.tool.stdlib_opcode import host_bytecode_spec
from opcode import EXTENDED_ARG, HAVE_ARGUMENT
from rpython.flowspace.argument import Signature
from rpython.flowspace.flowcontext import BytecodeCorruption

CO_GENERATOR = 0x0020
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008

def cpython_code_signature(code):
    "([list-of-arg-names], vararg-name-or-None, kwarg-name-or-None)."
    argcount = code.co_argcount
    argnames = list(code.co_varnames[:argcount])
    if code.co_flags & CO_VARARGS:
        varargname = code.co_varnames[argcount]
        argcount += 1
    else:
        varargname = None
    if code.co_flags & CO_VARKEYWORDS:
        kwargname = code.co_varnames[argcount]
        argcount += 1
    else:
        kwargname = None
    return Signature(argnames, varargname, kwargname)

class HostCode(object):
    """
    A wrapper around a native code object of the host interpreter
    """
    opnames = host_bytecode_spec.method_names

    def __init__(self, argcount, nlocals, stacksize, flags,
                     code, consts, names, varnames, filename,
                     name, firstlineno, lnotab, freevars):
        """Initialize a new code object"""
        self.co_name = name
        assert nlocals >= 0
        self.co_argcount = argcount
        self.co_nlocals = nlocals
        self.co_stacksize = stacksize
        self.co_flags = flags
        self.co_code = code
        self.consts = consts
        self.names = names
        self.co_varnames = varnames
        self.co_freevars = freevars
        self.co_filename = filename
        self.co_name = name
        self.co_firstlineno = firstlineno
        self.co_lnotab = lnotab
        self.signature = cpython_code_signature(self)

    @classmethod
    def _from_code(cls, code):
        """Initialize the code object from a real (CPython) one.
        """
        return cls(code.co_argcount,
                      code.co_nlocals,
                      code.co_stacksize,
                      code.co_flags,
                      code.co_code,
                      list(code.co_consts),
                      list(code.co_names),
                      list(code.co_varnames),
                      code.co_filename,
                      code.co_name,
                      code.co_firstlineno,
                      code.co_lnotab,
                      list(code.co_freevars))

    @property
    def formalargcount(self):
        """Total number of arguments passed into the frame, including *vararg
        and **varkwarg, if they exist."""
        return self.signature.scope_length()

    def read(self, pos):
        """
        Decode the instruction starting at position ``next_instr``.

        Returns (next_instr, opname, oparg).
        """
        co_code = self.co_code
        opcode = ord(co_code[pos])
        next_instr = pos + 1

        if opcode >= HAVE_ARGUMENT:
            lo = ord(co_code[next_instr])
            hi = ord(co_code[next_instr+1])
            next_instr += 2
            oparg = (hi * 256) | lo
        else:
            oparg = 0

        while opcode == EXTENDED_ARG:
            opcode = ord(co_code[next_instr])
            if opcode < HAVE_ARGUMENT:
                raise BytecodeCorruption
            lo = ord(co_code[next_instr+1])
            hi = ord(co_code[next_instr+2])
            next_instr += 3
            oparg = (oparg * 65536) | (hi * 256) | lo

        opname = self.opnames[opcode]
        return next_instr, opname, oparg

    @property
    def is_generator(self):
        return bool(self.co_flags & CO_GENERATOR)
