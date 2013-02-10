"""Flow graph building for generators"""

from rpython.flowspace.model import Block, Link, SpaceOperation, checkgraph
from rpython.flowspace.model import Variable, Constant
from rpython.translator.unsimplify import insert_empty_startblock
from rpython.translator.unsimplify import split_block
from rpython.translator.simplify import eliminate_empty_blocks, simplify_graph
from rpython.tool.sourcetools import func_with_new_name
from rpython.flowspace.argument import Signature


class AbstractPosition(object):
    _immutable_ = True
    _attrs_ = ()

def bootstrap_generator(graph):
    # This is the first copy of the graph.  We replace it with
    # a small bootstrap graph.
    GeneratorIterator = make_generatoriterator_class(graph)
    replace_graph_with_bootstrap(GeneratorIterator, graph)
    # We attach a 'next' method to the GeneratorIterator class
    # that will invoke the real function, based on a second
    # copy of the graph.
    attach_next_method(GeneratorIterator, graph)
    return graph

def tweak_generator_graph(graph):
    # This is the second copy of the graph.  Tweak it.
    GeneratorIterator = graph.func._generator_next_method_of_
    tweak_generator_body_graph(GeneratorIterator.Entry, graph)


def make_generatoriterator_class(graph):
    class GeneratorIterator(object):
        class Entry(AbstractPosition):
            _immutable_ = True
            varnames = get_variable_names(graph.startblock.inputargs)

        def __init__(self, entry):
            self.current = entry

        def __iter__(self):
            return self

    return GeneratorIterator

def replace_graph_with_bootstrap(GeneratorIterator, graph):
    Entry = GeneratorIterator.Entry
    newblock = Block(graph.startblock.inputargs)
    v_generator = Variable('generator')
    v_entry = Variable('entry')
    newblock.operations.append(
        SpaceOperation('simple_call', [Constant(Entry)], v_entry))
    assert len(graph.startblock.inputargs) == len(Entry.varnames)
    for v, name in zip(graph.startblock.inputargs, Entry.varnames):
        newblock.operations.append(
            SpaceOperation('setattr', [v_entry, Constant(name), v],
                           Variable()))
    newblock.operations.append(
        SpaceOperation('simple_call', [Constant(GeneratorIterator), v_entry],
                       v_generator))
    newblock.closeblock(Link([v_generator], graph.returnblock))
    graph.startblock = newblock

def attach_next_method(GeneratorIterator, graph):
    func = graph.func
    func = func_with_new_name(func, '%s__next' % (func.func_name,))
    func._generator_next_method_of_ = GeneratorIterator
    func._always_inline_ = True
    #
    def next(self):
        entry = self.current
        self.current = None
        assert entry is not None      # else, recursive generator invocation
        (next_entry, return_value) = func(entry)
        self.current = next_entry
        return return_value
    GeneratorIterator.next = next
    return func   # for debugging

def get_variable_names(variables):
    seen = set()
    result = []
    for v in variables:
        name = v._name.strip('_')
        while name in seen:
            name += '_'
        result.append('g_' + name)
        seen.add(name)
    return result

def _insert_reads(block, varnames):
    assert len(varnames) == len(block.inputargs)
    v_entry1 = Variable('entry')
    for i, name in enumerate(varnames):
        block.operations.insert(i,
            SpaceOperation('getattr', [v_entry1, Constant(name)],
                           block.inputargs[i]))
    block.inputargs = [v_entry1]

def tweak_generator_body_graph(Entry, graph):
    # First, always run simplify_graph in order to reduce the number of
    # variables passed around
    simplify_graph(graph)
    #
    assert graph.startblock.operations[0].opname == 'generator_mark'
    graph.startblock.operations.pop(0)
    #
    insert_empty_startblock(None, graph)
    _insert_reads(graph.startblock, Entry.varnames)
    Entry.block = graph.startblock
    #
    mappings = [Entry]
    #
    stopblock = Block([])
    v0 = Variable(); v1 = Variable()
    stopblock.operations = [
        SpaceOperation('simple_call', [Constant(StopIteration)], v0),
        SpaceOperation('type', [v0], v1),
        ]
    stopblock.closeblock(Link([v1, v0], graph.exceptblock))
    #
    for block in list(graph.iterblocks()):
        for exit in block.exits:
            if exit.target is graph.returnblock:
                exit.args = []
                exit.target = stopblock
        assert block is not stopblock
        for index in range(len(block.operations)-1, -1, -1):
            op = block.operations[index]
            if op.opname == 'yield':
                [v_yielded_value] = op.args
                del block.operations[index]
                newlink = split_block(None, block, index)
                newblock = newlink.target
                #
                class Resume(AbstractPosition):
                    _immutable_ = True
                    block = newblock
                Resume.__name__ = 'Resume%d' % len(mappings)
                mappings.append(Resume)
                varnames = get_variable_names(newlink.args)
                #
                _insert_reads(newblock, varnames)
                #
                v_resume = Variable('resume')
                block.operations.append(
                    SpaceOperation('simple_call', [Constant(Resume)],
                                   v_resume))
                for i, name in enumerate(varnames):
                    block.operations.append(
                        SpaceOperation('setattr', [v_resume, Constant(name),
                                                   newlink.args[i]],
                                       Variable()))
                v_pair = Variable('pair')
                block.operations.append(
                    SpaceOperation('newtuple', [v_resume, v_yielded_value],
                                   v_pair))
                newlink.args = [v_pair]
                newlink.target = graph.returnblock
    #
    regular_entry_block = Block([Variable('entry')])
    block = regular_entry_block
    for Resume in mappings:
        v_check = Variable()
        block.operations.append(
            SpaceOperation('simple_call', [Constant(isinstance),
                                           block.inputargs[0],
                                           Constant(Resume)],
                           v_check))
        block.exitswitch = v_check
        link1 = Link([block.inputargs[0]], Resume.block)
        link1.exitcase = True
        nextblock = Block([Variable('entry')])
        link2 = Link([block.inputargs[0]], nextblock)
        link2.exitcase = False
        block.closeblock(link1, link2)
        block = nextblock
    block.closeblock(Link([Constant(AssertionError),
                           Constant(AssertionError("bad generator class"))],
                          graph.exceptblock))
    graph.startblock = regular_entry_block
    graph.signature = Signature(['entry'])
    graph.defaults = ()
    checkgraph(graph)
    eliminate_empty_blocks(graph)
