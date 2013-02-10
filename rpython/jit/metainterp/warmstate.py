import sys, weakref
from rpython.rtyper.lltypesystem import lltype, llmemory, rstr, rffi
from rpython.rtyper.ootypesystem import ootype
from rpython.rtyper.annlowlevel import hlstr, cast_base_ptr_to_instance
from rpython.rtyper.annlowlevel import cast_object_to_ptr
from rpython.rlib.objectmodel import specialize, we_are_translated, r_dict
from rpython.rlib.rarithmetic import intmask
from rpython.rlib.nonconst import NonConstant
from rpython.rlib.unroll import unrolling_iterable
from rpython.rlib.jit import PARAMETERS
from rpython.rlib.jit import BaseJitCell
from rpython.rlib.debug import debug_start, debug_stop, debug_print
from rpython.jit.metainterp import history
from rpython.jit.codewriter import support, heaptracker, longlong
from rpython.tool.sourcetools import func_with_new_name

# ____________________________________________________________

@specialize.arg(0)
def specialize_value(TYPE, x):
    """'x' must be a Signed, a GCREF or a FLOATSTORAGE.
    This function casts it to a more specialized type, like Char or Ptr(..).
    """
    INPUT = lltype.typeOf(x)
    if INPUT is lltype.Signed:
        if isinstance(TYPE, lltype.Ptr) and TYPE.TO._gckind == 'raw':
            # non-gc pointer
            return rffi.cast(TYPE, x)
        elif TYPE is lltype.SingleFloat:
            return longlong.int2singlefloat(x)
        else:
            return lltype.cast_primitive(TYPE, x)
    elif INPUT is longlong.FLOATSTORAGE:
        if longlong.is_longlong(TYPE):
            return rffi.cast(TYPE, x)
        assert TYPE is lltype.Float
        return longlong.getrealfloat(x)
    else:
        return lltype.cast_opaque_ptr(TYPE, x)

@specialize.ll()
def unspecialize_value(value):
    """Casts 'value' to a Signed, a GCREF or a FLOATSTORAGE."""
    if isinstance(lltype.typeOf(value), lltype.Ptr):
        if lltype.typeOf(value).TO._gckind == 'gc':
            return lltype.cast_opaque_ptr(llmemory.GCREF, value)
        else:
            adr = llmemory.cast_ptr_to_adr(value)
            return heaptracker.adr2int(adr)
    elif isinstance(lltype.typeOf(value), ootype.OOType):
        return ootype.cast_to_object(value)
    elif isinstance(value, float):
        return longlong.getfloatstorage(value)
    else:
        return lltype.cast_primitive(lltype.Signed, value)

@specialize.arg(0)
def unwrap(TYPE, box):
    if TYPE is lltype.Void:
        return None
    if isinstance(TYPE, lltype.Ptr):
        if TYPE.TO._gckind == "gc":
            return box.getref(TYPE)
        else:
            return llmemory.cast_adr_to_ptr(box.getaddr(), TYPE)
    if isinstance(TYPE, ootype.OOType):
        return box.getref(TYPE)
    if TYPE == lltype.Float:
        return box.getfloat()
    else:
        return lltype.cast_primitive(TYPE, box.getint())

@specialize.ll()
def wrap(cpu, value, in_const_box=False):
    if isinstance(lltype.typeOf(value), lltype.Ptr):
        if lltype.typeOf(value).TO._gckind == 'gc':
            value = lltype.cast_opaque_ptr(llmemory.GCREF, value)
            if in_const_box:
                return history.ConstPtr(value)
            else:
                return history.BoxPtr(value)
        else:
            adr = llmemory.cast_ptr_to_adr(value)
            value = heaptracker.adr2int(adr)
            # fall through to the end of the function
    elif isinstance(lltype.typeOf(value), ootype.OOType):
        value = ootype.cast_to_object(value)
        if in_const_box:
            return history.ConstObj(value)
        else:
            return history.BoxObj(value)
    elif (isinstance(value, float) or
          longlong.is_longlong(lltype.typeOf(value))):
        if isinstance(value, float):
            value = longlong.getfloatstorage(value)
        else:
            value = rffi.cast(lltype.SignedLongLong, value)
        if in_const_box:
            return history.ConstFloat(value)
        else:
            return history.BoxFloat(value)
    elif isinstance(value, str) or isinstance(value, unicode):
        assert len(value) == 1     # must be a character
        value = ord(value)
    elif lltype.typeOf(value) is lltype.SingleFloat:
        value = longlong.singlefloat2int(value)
    else:
        value = intmask(value)
    if in_const_box:
        return history.ConstInt(value)
    else:
        return history.BoxInt(value)

@specialize.arg(0)
def equal_whatever(TYPE, x, y):
    if isinstance(TYPE, lltype.Ptr):
        if TYPE.TO is rstr.STR or TYPE.TO is rstr.UNICODE:
            return rstr.LLHelpers.ll_streq(x, y)
    if TYPE is ootype.String or TYPE is ootype.Unicode:
        return x.ll_streq(y)
    return x == y

@specialize.arg(0)
def hash_whatever(TYPE, x):
    # Hash of lltype or ootype object.
    # Only supports strings, unicodes and regular instances,
    # as well as primitives that can meaningfully be cast to Signed.
    if isinstance(TYPE, lltype.Ptr) and TYPE.TO._gckind == 'gc':
        if TYPE.TO is rstr.STR or TYPE.TO is rstr.UNICODE:
            return rstr.LLHelpers.ll_strhash(x)    # assumed not null
        else:
            if x:
                return lltype.identityhash(x)
            else:
                return 0
    elif TYPE is ootype.String or TYPE is ootype.Unicode:
        return x.ll_hash()
    elif isinstance(TYPE, ootype.OOType):
        if x:
            return ootype.identityhash(x)
        else:
            return 0
    else:
        return rffi.cast(lltype.Signed, x)


class JitCell(BaseJitCell):
    # the counter can mean the following things:
    #     counter >=  0: not yet traced, wait till threshold is reached
    #     counter == -1: there is an entry bridge for this cell
    #     counter == -2: tracing is currently going on for this cell
    counter = 0
    dont_trace_here = False
    extra_delay = chr(0)
    wref_procedure_token = None

    def get_procedure_token(self):
        if self.wref_procedure_token is not None:
            token = self.wref_procedure_token()
            if token and not token.invalidated:
                return token
        return None

    def set_procedure_token(self, token):
        self.wref_procedure_token = self._makeref(token)

    def _makeref(self, token):
        assert token is not None
        return weakref.ref(token)

# ____________________________________________________________


class WarmEnterState(object):
    THRESHOLD_LIMIT = sys.maxint // 2

    def __init__(self, warmrunnerdesc, jitdriver_sd):
        "NOT_RPYTHON"
        self.warmrunnerdesc = warmrunnerdesc
        self.jitdriver_sd = jitdriver_sd
        if warmrunnerdesc is not None:       # for tests
            self.cpu = warmrunnerdesc.cpu
        try:
            self.profiler = warmrunnerdesc.metainterp_sd.profiler
        except AttributeError:       # for tests
            self.profiler = None
        # initialize the state with the default values of the
        # parameters specified in rlib/jit.py
        for name, default_value in PARAMETERS.items():
            meth = getattr(self, 'set_param_' + name)
            meth(default_value)

    def _compute_threshold(self, threshold):
        if threshold <= 0:
            return 0 # never reach the THRESHOLD_LIMIT
        if threshold < 2:
            threshold = 2
        return (self.THRESHOLD_LIMIT // threshold) + 1
        # the number is at least 1, and at most about half THRESHOLD_LIMIT

    def set_param_threshold(self, threshold):
        self.increment_threshold = self._compute_threshold(threshold)

    def set_param_function_threshold(self, threshold):
        self.increment_function_threshold = self._compute_threshold(threshold)

    def set_param_trace_eagerness(self, value):
        self.trace_eagerness = value

    def set_param_trace_limit(self, value):
        self.trace_limit = value

    def set_param_inlining(self, value):
        self.inlining = value

    def set_param_enable_opts(self, value):
        from rpython.jit.metainterp.optimizeopt import ALL_OPTS_DICT, ALL_OPTS_NAMES

        d = {}
        if NonConstant(False):
            value = 'blah' # not a constant ''
        if value is None or value == 'all':
            value = ALL_OPTS_NAMES
        for name in value.split(":"):
            if name:
                if name not in ALL_OPTS_DICT:
                    raise ValueError('Unknown optimization ' + name)
                d[name] = None
        self.enable_opts = d

    def set_param_loop_longevity(self, value):
        # note: it's a global parameter, not a per-jitdriver one
        if (self.warmrunnerdesc is not None and
            self.warmrunnerdesc.memory_manager is not None):   # all for tests
            self.warmrunnerdesc.memory_manager.set_max_age(value)

    def set_param_retrace_limit(self, value):
        if self.warmrunnerdesc:
            if self.warmrunnerdesc.memory_manager:
                self.warmrunnerdesc.memory_manager.retrace_limit = value

    def set_param_max_retrace_guards(self, value):
        if self.warmrunnerdesc:
            if self.warmrunnerdesc.memory_manager:
                self.warmrunnerdesc.memory_manager.max_retrace_guards = value

    def set_param_max_unroll_loops(self, value):
        if self.warmrunnerdesc:
            if self.warmrunnerdesc.memory_manager:
                self.warmrunnerdesc.memory_manager.max_unroll_loops = value

    def disable_noninlinable_function(self, greenkey):
        cell = self.jit_cell_at_key(greenkey)
        cell.dont_trace_here = True
        debug_start("jit-disableinlining")
        loc = self.get_location_str(greenkey)
        debug_print("disabled inlining", loc)
        debug_stop("jit-disableinlining")

    def attach_procedure_to_interp(self, greenkey, procedure_token):
        cell = self.jit_cell_at_key(greenkey)
        old_token = cell.get_procedure_token()
        cell.set_procedure_token(procedure_token)
        cell.counter = -1       # valid procedure bridge attached
        if old_token is not None:
            self.cpu.redirect_call_assembler(old_token, procedure_token)
            # procedure_token is also kept alive by any loop that used
            # to point to old_token.  Actually freeing old_token early
            # is a pointless optimization (it is tiny).
            old_token.record_jump_to(procedure_token)

    # ----------

    def make_entry_point(self):
        "NOT_RPYTHON"
        if hasattr(self, 'maybe_compile_and_run'):
            return self.maybe_compile_and_run

        warmrunnerdesc = self.warmrunnerdesc
        metainterp_sd = warmrunnerdesc.metainterp_sd
        jitdriver_sd = self.jitdriver_sd
        vinfo = jitdriver_sd.virtualizable_info
        index_of_virtualizable = jitdriver_sd.index_of_virtualizable
        num_green_args = jitdriver_sd.num_green_args
        get_jitcell = self.make_jitcell_getter()
        self.make_jitdriver_callbacks()
        confirm_enter_jit = self.confirm_enter_jit
        range_red_args = unrolling_iterable(
            range(num_green_args, num_green_args + jitdriver_sd.num_red_args))
        # get a new specialized copy of the method
        ARGS = []
        for kind in jitdriver_sd.red_args_types:
            if kind == 'int':
                ARGS.append(lltype.Signed)
            elif kind == 'ref':
                ARGS.append(llmemory.GCREF)
            elif kind == 'float':
                ARGS.append(longlong.FLOATSTORAGE)
            else:
                assert 0, kind
        func_execute_token = self.cpu.make_execute_token(*ARGS)
        cpu = self.cpu

        def execute_assembler(loop_token, *args):
            # Call the backend to run the 'looptoken' with the given
            # input args.
            deadframe = func_execute_token(loop_token, *args)
            #
            # If we have a virtualizable, we have to reset its
            # 'vable_token' field afterwards
            if vinfo is not None:
                virtualizable = args[index_of_virtualizable]
                virtualizable = vinfo.cast_gcref_to_vtype(virtualizable)
                vinfo.reset_vable_token(virtualizable)
            #
            # Record in the memmgr that we just ran this loop,
            # so that it will keep it alive for a longer time
            warmrunnerdesc.memory_manager.keep_loop_alive(loop_token)
            #
            # Handle the failure
            fail_descr = cpu.get_latest_descr(deadframe)
            fail_descr.handle_fail(deadframe, metainterp_sd, jitdriver_sd)
            #
            assert 0, "should have raised"

        def bound_reached(cell, *args):
            # bound reached, but we do a last check: if it is the first
            # time we reach the bound, or if another loop or bridge was
            # compiled since the last time we reached it, then decrease
            # the counter by a few percents instead.  It should avoid
            # sudden bursts of JIT-compilation, and also corner cases
            # where we suddenly compile more than one loop because all
            # counters reach the bound at the same time, but where
            # compiling all but the first one is pointless.
            curgen = warmrunnerdesc.memory_manager.current_generation
            curgen = chr(intmask(curgen) & 0xFF)    # only use 8 bits
            if we_are_translated() and curgen != cell.extra_delay:
                cell.counter = int(self.THRESHOLD_LIMIT * 0.98)
                cell.extra_delay = curgen
                return
            #
            if not confirm_enter_jit(*args):
                cell.counter = 0
                return
            # start tracing
            from rpython.jit.metainterp.pyjitpl import MetaInterp
            metainterp = MetaInterp(metainterp_sd, jitdriver_sd)
            # set counter to -2, to mean "tracing in effect"
            cell.counter = -2
            try:
                metainterp.compile_and_run_once(jitdriver_sd, *args)
            finally:
                if cell.counter == -2:
                    cell.counter = 0

        def maybe_compile_and_run(threshold, *args):
            """Entry point to the JIT.  Called at the point with the
            can_enter_jit() hint.
            """
            # look for the cell corresponding to the current greenargs
            greenargs = args[:num_green_args]
            cell = get_jitcell(True, *greenargs)

            if cell.counter >= 0:
                # update the profiling counter
                n = cell.counter + threshold
                if n <= self.THRESHOLD_LIMIT:       # bound not reached
                    cell.counter = n
                    return
                else:
                    bound_reached(cell, *args)
                    return
            else:
                if cell.counter != -1:
                    assert cell.counter == -2
                    # tracing already happening in some outer invocation of
                    # this function. don't trace a second time.
                    return
                if not confirm_enter_jit(*args):
                    return
                # machine code was already compiled for these greenargs
                procedure_token = cell.get_procedure_token()
                if procedure_token is None:   # it was a weakref that has been freed
                    cell.counter = 0
                    return
                # extract and unspecialize the red arguments to pass to
                # the assembler
                execute_args = ()
                for i in range_red_args:
                    execute_args += (unspecialize_value(args[i]), )
                # run it!  this executes until interrupted by an exception
                execute_assembler(procedure_token, *execute_args)
            #
            assert 0, "should not reach this point"

        maybe_compile_and_run._dont_inline_ = True
        self.maybe_compile_and_run = maybe_compile_and_run
        self.execute_assembler = execute_assembler
        return maybe_compile_and_run

    # ----------

    def make_unwrap_greenkey(self):
        "NOT_RPYTHON"
        if hasattr(self, 'unwrap_greenkey'):
            return self.unwrap_greenkey
        #
        jitdriver_sd = self.jitdriver_sd
        green_args_spec = unrolling_iterable(jitdriver_sd._green_args_spec)
        #
        def unwrap_greenkey(greenkey):
            greenargs = ()
            i = 0
            for TYPE in green_args_spec:
                greenbox = greenkey[i]
                assert isinstance(greenbox, history.Const)
                value = unwrap(TYPE, greenbox)
                greenargs += (value,)
                i = i + 1
            return greenargs
        #
        unwrap_greenkey._always_inline_ = True
        self.unwrap_greenkey = unwrap_greenkey
        return unwrap_greenkey

    # ----------

    def make_jitcell_getter(self):
        "NOT_RPYTHON"
        if hasattr(self, 'jit_getter'):
            return self.jit_getter
        #
        if self.jitdriver_sd._get_jitcell_at_ptr is None:
            jit_getter = self._make_jitcell_getter_default()
        else:
            jit_getter = self._make_jitcell_getter_custom()
        #
        unwrap_greenkey = self.make_unwrap_greenkey()
        #
        def jit_cell_at_key(greenkey):
            greenargs = unwrap_greenkey(greenkey)
            return jit_getter(True, *greenargs)
        self.jit_cell_at_key = jit_cell_at_key
        self.jit_getter = jit_getter
        #
        return jit_getter

    def _make_jitcell_getter_default(self):
        "NOT_RPYTHON"
        jitdriver_sd = self.jitdriver_sd
        green_args_spec = unrolling_iterable(jitdriver_sd._green_args_spec)
        #
        def comparekey(greenargs1, greenargs2):
            i = 0
            for TYPE in green_args_spec:
                if not equal_whatever(TYPE, greenargs1[i], greenargs2[i]):
                    return False
                i = i + 1
            return True
        #
        def hashkey(greenargs):
            x = 0x345678
            i = 0
            for TYPE in green_args_spec:
                item = greenargs[i]
                y = hash_whatever(TYPE, item)
                x = intmask((1000003 * x) ^ y)
                i = i + 1
            return x
        #
        jitcell_dict = r_dict(comparekey, hashkey)
        try:
            self.warmrunnerdesc.stats.jitcell_dicts.append(jitcell_dict)
        except AttributeError:
            pass
        #
        def _cleanup_dict():
            minimum = self.THRESHOLD_LIMIT // 20     # minimum 5%
            killme = []
            for key, cell in jitcell_dict.iteritems():
                if cell.counter >= 0:
                    cell.counter = int(cell.counter * 0.92)
                    if cell.counter < minimum:
                        killme.append(key)
                elif (cell.counter == -1
                      and cell.get_procedure_token() is None):
                    killme.append(key)
            for key in killme:
                del jitcell_dict[key]
        #
        def _maybe_cleanup_dict():
            # Once in a while, rarely, when too many entries have
            # been put in the jitdict_dict, we do a cleanup phase:
            # we decay all counters and kill entries with a too
            # low counter.
            self._trigger_automatic_cleanup += 1
            if self._trigger_automatic_cleanup > 20000:
                self._trigger_automatic_cleanup = 0
                _cleanup_dict()
        #
        self._trigger_automatic_cleanup = 0
        self._jitcell_dict = jitcell_dict       # for tests
        #
        def get_jitcell(build, *greenargs):
            try:
                cell = jitcell_dict[greenargs]
            except KeyError:
                if not build:
                    return None
                _maybe_cleanup_dict()
                cell = JitCell()
                jitcell_dict[greenargs] = cell
            return cell
        return get_jitcell

    def _make_jitcell_getter_custom(self):
        "NOT_RPYTHON"
        rtyper = self.warmrunnerdesc.rtyper
        get_jitcell_at_ptr = self.jitdriver_sd._get_jitcell_at_ptr
        set_jitcell_at_ptr = self.jitdriver_sd._set_jitcell_at_ptr
        lltohlhack = {}
        # note that there is no equivalent of _maybe_cleanup_dict()
        # in the case of custom getters.  We assume that the interpreter
        # stores the JitCells on some objects that can go away by GC,
        # like the PyCode objects in PyPy.
        #
        def get_jitcell(build, *greenargs):
            fn = support.maybe_on_top_of_llinterp(rtyper, get_jitcell_at_ptr)
            cellref = fn(*greenargs)
            # <hacks>
            if we_are_translated():
                BASEJITCELL = lltype.typeOf(cellref)
                cell = cast_base_ptr_to_instance(JitCell, cellref)
            else:
                if isinstance(cellref, (BaseJitCell, type(None))):
                    BASEJITCELL = None
                    cell = cellref
                else:
                    BASEJITCELL = lltype.typeOf(cellref)
                    if cellref:
                        cell = lltohlhack[rtyper.type_system.deref(cellref)]
                    else:
                        cell = None
            if not build:
                return cell
            if cell is None:
                cell = JitCell()
                # <hacks>
                if we_are_translated():
                    cellref = cast_object_to_ptr(BASEJITCELL, cell)
                else:
                    if BASEJITCELL is None:
                        cellref = cell
                    else:
                        if isinstance(BASEJITCELL, lltype.Ptr):
                            cellref = lltype.malloc(BASEJITCELL.TO)
                        elif isinstance(BASEJITCELL, ootype.Instance):
                            cellref = ootype.new(BASEJITCELL)
                        else:
                            assert False, "no clue"
                        lltohlhack[rtyper.type_system.deref(cellref)] = cell
                # </hacks>
                fn = support.maybe_on_top_of_llinterp(rtyper,
                                                      set_jitcell_at_ptr)
                fn(cellref, *greenargs)
            return cell
        return get_jitcell

    # ----------

    def make_jitdriver_callbacks(self):
        if hasattr(self, 'get_location_str'):
            return
        #
        warmrunnerdesc = self.warmrunnerdesc
        unwrap_greenkey = self.make_unwrap_greenkey()
        jit_getter = self.make_jitcell_getter()
        jd = self.jitdriver_sd
        cpu = self.cpu

        def can_inline_greenargs(*greenargs):
            if can_never_inline(*greenargs):
                return False
            cell = jit_getter(False, *greenargs)
            if cell is not None and cell.dont_trace_here:
                return False
            return True
        def can_inline_callable(greenkey):
            greenargs = unwrap_greenkey(greenkey)
            return can_inline_greenargs(*greenargs)
        self.can_inline_greenargs = can_inline_greenargs
        self.can_inline_callable = can_inline_callable

        if jd._should_unroll_one_iteration_ptr is None:
            def should_unroll_one_iteration(greenkey):
                return False
        else:
            rtyper = self.warmrunnerdesc.rtyper
            inline_ptr = jd._should_unroll_one_iteration_ptr
            def should_unroll_one_iteration(greenkey):
                greenargs = unwrap_greenkey(greenkey)
                fn = support.maybe_on_top_of_llinterp(rtyper, inline_ptr)
                return fn(*greenargs)
        self.should_unroll_one_iteration = should_unroll_one_iteration
        
        redargtypes = ''.join([kind[0] for kind in jd.red_args_types])

        def get_assembler_token(greenkey):
            cell = self.jit_cell_at_key(greenkey)
            procedure_token = cell.get_procedure_token()
            if procedure_token is None:
                from rpython.jit.metainterp.compile import compile_tmp_callback
                if cell.counter == -1:    # used to be a valid entry bridge,
                    cell.counter = 0      # but was freed in the meantime.
                memmgr = warmrunnerdesc.memory_manager
                procedure_token = compile_tmp_callback(cpu, jd, greenkey,
                                                       redargtypes, memmgr)
                cell.set_procedure_token(procedure_token)
            return procedure_token
        self.get_assembler_token = get_assembler_token

        #
        get_location_ptr = self.jitdriver_sd._get_printable_location_ptr
        if get_location_ptr is None:
            missing = '(no jitdriver.get_printable_location!)'
            def get_location_str(greenkey):
                return missing
        else:
            rtyper = self.warmrunnerdesc.rtyper
            unwrap_greenkey = self.make_unwrap_greenkey()
            #
            def get_location_str(greenkey):
                greenargs = unwrap_greenkey(greenkey)
                fn = support.maybe_on_top_of_llinterp(rtyper, get_location_ptr)
                llres = fn(*greenargs)
                if not we_are_translated() and isinstance(llres, str):
                    return llres
                return hlstr(llres)
        self.get_location_str = get_location_str
        #
        confirm_enter_jit_ptr = self.jitdriver_sd._confirm_enter_jit_ptr
        if confirm_enter_jit_ptr is None:
            def confirm_enter_jit(*args):
                return True
        else:
            rtyper = self.warmrunnerdesc.rtyper
            #
            def confirm_enter_jit(*args):
                fn = support.maybe_on_top_of_llinterp(rtyper,
                                                      confirm_enter_jit_ptr)
                return fn(*args)
        self.confirm_enter_jit = confirm_enter_jit
        #
        can_never_inline_ptr = self.jitdriver_sd._can_never_inline_ptr
        if can_never_inline_ptr is None:
            def can_never_inline(*greenargs):
                return False
        else:
            rtyper = self.warmrunnerdesc.rtyper
            #
            def can_never_inline(*greenargs):
                fn = support.maybe_on_top_of_llinterp(rtyper,
                                                      can_never_inline_ptr)
                return fn(*greenargs)
        self.can_never_inline = can_never_inline
