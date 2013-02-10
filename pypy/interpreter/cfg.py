
def make_cfg(code, w_globals)
"""
  w_globals : comes from the frame.w_globals 
  w_closure : comes from cells
"""
#        _assert_rpythonic(func)
        if (code.is_generator and
                not hasattr(func, '_generator_next_method_of_')):
            graph = PyGraph(func, code)
            block = graph.startblock
            for name, w_value in zip(code.co_varnames, block.framestate.mergeable):
                if isinstance(w_value, Variable):
                    w_value.rename(name)
            return bootstrap_generator(graph)
        graph = PyGraph(func, code)
        frame = self.frame = FlowSpaceFrame(self, graph, code)
        frame.build_flow()
        fixeggblocks(graph)
        checkgraph(graph)
        if code.is_generator:
            tweak_generator_graph(graph)
        return graph


import pypy.tool.stdlib_opcode as libopcode

opmap = libopcode.opmap   # name -> code
opname = libopcode.opname # code -> name
OP_METHOD_MAP = {}
for opcode, name in opname.items():
    if name in SPECIALS:
        methodname = name
    else:
        methodname = "GENERIC_BYTECODE"
    OP_METHOD_MAP[opcode] = methodname

class ByteCodeVisitor(object):
    """
    Each bytecode gets called with args,
    current instruction
    and next instruction

    Importantly, this really only works on the code for a 
    single frame / function.
    """
    def __init__(self, co_code):
        self.code = co_code
        self.out_flows = {} # mapping from code offset to possible exits
        self.dispatch(0)    # first instruction is le zero.
    def dispatch(self, instr):
        last_instr = intmask(instr)
        opcode = ord(self.code[instr])
        instr += 1
        if opcode >= self.HAVE_ARGUMENT:
            lo = ord(co_code[instr])
            hi = ord(co_code[instr + 1])
            instr += 2
            oparg = (hi * 256) | lo
        else:
            oparg = 0
        if last_instr in self.loop_stack:
            z = self.loop_stack.pop()
            if last_instr != z:
                raise BytecodeCorruption("seemingly loop ordering problem!")

        methodname = OP_METHOD_MAP[opcode]
        try:
            meth = getattr(self, methodname)
        except AttributeError:
            raise BytecodeCorruption("unimplemented opcode, ofs=%d, "
                                     "code=%d, name=%s" %
                                     (last_instr, opcode,
                                      methodname))
        self.out_flows[instr] = meth(oparg, instr)

    def GENERIC_BYTECODE(self, oparg, next_instr):
        return (next_instr,) # no branch!
    def STOP_CODE(self, oparg, next_instr):
        return ()
    def RETURN_VALUE(self, oparg, next_instr):
        return ()
#  ... interestingly, I think YIELDs are exactly like ``normal'' ops.
#    def YIELD_VALUE(self, oparg, instr, next_instr):
    def FOR_ITER(self, jumpby, next_instr):
        return (next_instr, next_instr + jumpby)
    def JUMP_FORWARD(self, jumpby, next_instr):
        return (next_instr + jumpby,)
    def JUMP_IF_FALSE_OR_POP(self, target, next_instr):
        return (target, next_instr)
    def JUMP_IF_TRUE_OR_POP(self, target, next_instr):
        return (target, next_instr)
    def JUMP_ABSOLUTE(self, jumpto, next_instr):
        return (jumpto, )
    def POP_JUMP_IF_FALSE(self, target, next_instr):
        return (target, next_instr)
    def POP_JUMP_IF_TRUE(self, target, next_instr):
        return (target, next_instr)
    def CONTINUE_LOOP(self, startofloop, next_instr):
        return (startofloop,) # 
    def BREAK_LOOP(self):
        endofloop = self.loop_stack.pop()
        return (endofloop,) # 
    def SETUP_LOOP(self, offsettoend, next_instr):
        self.loop_stack.append(offsettoend + next_instr) # pushes the end of the loop
        return (next_instr,)
    def SETUP_EXCEPT(self, offsettoend, next_instr):
        return (next_instr + offsettoend,)
    def SETUP_FINALLY(self, offsettoend, next_instr)
        return (next_instr + offsettoend,)
    def END_FINALLY(self, oparg, next_instr):
        # oof. we could get here from almost anywhere.
        # complicates the analysis to say the frackin' least.
        # for the moment, we'll punt on this.
        # RATIONALE: because we use CFG to compute ipdom relationship,
        # we will over-taint in these ``exception`` cases (because we'll miss
        # ipdoms and therefore will taint things we wouldn't have normally tainted.)
        return ()
    def RAISE_VARARGS(self):
        return () # think about whether or not this is "conservative"
#    def SETUP_WITH(self):        pretty sure that with's don't have internal "exit" instructions...
#        return (next_instr,)

class AnonyPyGraph(PyGraph):
    def __init__(self, func, code)
