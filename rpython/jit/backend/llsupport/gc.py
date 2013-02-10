import os
from rpython.rlib import rgc
from rpython.rlib.objectmodel import we_are_translated, specialize
from rpython.rlib.rarithmetic import ovfcheck
from rpython.rtyper.lltypesystem import lltype, llmemory, rffi, rclass, rstr
from rpython.rtyper.lltypesystem import llgroup
from rpython.rtyper.lltypesystem.lloperation import llop
from rpython.rtyper.annlowlevel import llhelper
from rpython.translator.tool.cbuild import ExternalCompilationInfo
from rpython.jit.codewriter import heaptracker
from rpython.jit.metainterp.history import ConstPtr, AbstractDescr
from rpython.jit.metainterp.resoperation import ResOperation, rop
from rpython.jit.backend.llsupport import symbolic, jitframe
from rpython.jit.backend.llsupport.symbolic import WORD
from rpython.jit.backend.llsupport.descr import SizeDescr, ArrayDescr
from rpython.jit.backend.llsupport.descr import GcCache, get_field_descr
from rpython.jit.backend.llsupport.descr import get_array_descr
from rpython.jit.backend.llsupport.descr import get_call_descr
from rpython.jit.backend.llsupport.rewrite import GcRewriterAssembler
from rpython.rtyper.memory.gctransform import asmgcroot

# ____________________________________________________________

class GcLLDescription(GcCache):

    def __init__(self, gcdescr, translator=None, rtyper=None):
        GcCache.__init__(self, translator is not None, rtyper)
        self.gcdescr = gcdescr
        if translator and translator.config.translation.gcremovetypeptr:
            self.fielddescr_vtable = None
        else:
            self.fielddescr_vtable = get_field_descr(self, rclass.OBJECT,
                                                     'typeptr')
        self._generated_functions = []

    def _setup_str(self):
        self.str_descr     = get_array_descr(self, rstr.STR)
        self.unicode_descr = get_array_descr(self, rstr.UNICODE)

    def generate_function(self, funcname, func, ARGS, RESULT=llmemory.GCREF):
        """Generates a variant of malloc with the given name and the given
        arguments.  It should return NULL if out of memory.  If it raises
        anything, it must be an optional MemoryError.
        """
        FUNCPTR = lltype.Ptr(lltype.FuncType(ARGS, RESULT))
        descr = get_call_descr(self, ARGS, RESULT)
        setattr(self, funcname, func)
        setattr(self, funcname + '_FUNCPTR', FUNCPTR)
        setattr(self, funcname + '_descr', descr)
        self._generated_functions.append(funcname)

    @specialize.arg(1)
    def get_malloc_fn(self, funcname):
        func = getattr(self, funcname)
        FUNC = getattr(self, funcname + '_FUNCPTR')
        return llhelper(FUNC, func)

    @specialize.arg(1)
    def get_malloc_fn_addr(self, funcname):
        ll_func = self.get_malloc_fn(funcname)
        return heaptracker.adr2int(llmemory.cast_ptr_to_adr(ll_func))

    def _freeze_(self):
        return True
    def initialize(self):
        pass
    def do_write_barrier(self, gcref_struct, gcref_newptr):
        pass
    def can_use_nursery_malloc(self, size):
        return False
    def has_write_barrier_class(self):
        return None
    def freeing_block(self, start, stop):
        pass
    def get_nursery_free_addr(self):
        raise NotImplementedError
    def get_nursery_top_addr(self):
        raise NotImplementedError

    def gc_malloc(self, sizedescr):
        """Blackhole: do a 'bh_new'.  Also used for 'bh_new_with_vtable',
        with the vtable pointer set manually afterwards."""
        assert isinstance(sizedescr, SizeDescr)
        return self._bh_malloc(sizedescr)

    def gc_malloc_array(self, num_elem, arraydescr):
        assert isinstance(arraydescr, ArrayDescr)
        return self._bh_malloc_array(num_elem, arraydescr)

    def gc_malloc_str(self, num_elem):
        return self._bh_malloc_array(num_elem, self.str_descr)

    def gc_malloc_unicode(self, num_elem):
        return self._bh_malloc_array(num_elem, self.unicode_descr)

    def _record_constptrs(self, op, gcrefs_output_list):
        for i in range(op.numargs()):
            v = op.getarg(i)
            if isinstance(v, ConstPtr) and bool(v.value):
                p = v.value
                rgc._make_sure_does_not_move(p)
                gcrefs_output_list.append(p)

    def rewrite_assembler(self, cpu, operations, gcrefs_output_list):
        rewriter = GcRewriterAssembler(self, cpu)
        newops = rewriter.rewrite(operations)
        # record all GCREFs, because the GC (or Boehm) cannot see them and
        # keep them alive if they end up as constants in the assembler
        for op in newops:
            self._record_constptrs(op, gcrefs_output_list)
        return newops

    @specialize.memo()
    def getframedescrs(self, cpu):
        descrs = JitFrameDescrs()
        descrs.arraydescr = cpu.arraydescrof(jitframe.DEADFRAME)
        descrs.as_int = cpu.interiorfielddescrof(jitframe.DEADFRAME,
                                                 'int', 'jf_values')
        descrs.as_ref = cpu.interiorfielddescrof(jitframe.DEADFRAME,
                                                 'ref', 'jf_values')
        descrs.as_float = cpu.interiorfielddescrof(jitframe.DEADFRAME,
                                                   'float', 'jf_values')
        descrs.jf_descr = cpu.fielddescrof(jitframe.DEADFRAME, 'jf_descr')
        descrs.jf_guard_exc = cpu.fielddescrof(jitframe.DEADFRAME,
                                               'jf_guard_exc')
        return descrs

class JitFrameDescrs:
    def _freeze_(self):
        return True

# ____________________________________________________________

class GcLLDescr_boehm(GcLLDescription):
    kind                  = 'boehm'
    moving_gc             = False
    round_up              = False
    gcrootmap             = None
    write_barrier_descr   = None
    fielddescr_tid        = None
    str_type_id           = 0
    unicode_type_id       = 0
    get_malloc_slowpath_addr = None

    @classmethod
    def configure_boehm_once(cls):
        """ Configure boehm only once, since we don't cache failures
        """
        if hasattr(cls, 'malloc_fn_ptr'):
            return cls.malloc_fn_ptr
        from rpython.rtyper.tool import rffi_platform
        compilation_info = rffi_platform.configure_boehm()

        # on some platform GC_init is required before any other
        # GC_* functions, call it here for the benefit of tests
        # XXX move this to tests
        init_fn_ptr = rffi.llexternal("GC_init",
                                      [], lltype.Void,
                                      compilation_info=compilation_info,
                                      sandboxsafe=True,
                                      _nowrapper=True)
        init_fn_ptr()

        # Versions 6.x of libgc needs to use GC_local_malloc().
        # Versions 7.x of libgc removed this function; GC_malloc() has
        # the same behavior if libgc was compiled with
        # THREAD_LOCAL_ALLOC.
        class CConfig:
            _compilation_info_ = compilation_info
            HAS_LOCAL_MALLOC = rffi_platform.Has("GC_local_malloc")
        config = rffi_platform.configure(CConfig)
        if config['HAS_LOCAL_MALLOC']:
            GC_MALLOC = "GC_local_malloc"
        else:
            GC_MALLOC = "GC_malloc"
        malloc_fn_ptr = rffi.llexternal(GC_MALLOC,
                                        [lltype.Signed], # size_t, but good enough
                                        llmemory.GCREF,
                                        compilation_info=compilation_info,
                                        sandboxsafe=True,
                                        _nowrapper=True)
        cls.malloc_fn_ptr = malloc_fn_ptr
        return malloc_fn_ptr

    def __init__(self, gcdescr, translator, rtyper):
        GcLLDescription.__init__(self, gcdescr, translator, rtyper)
        # grab a pointer to the Boehm 'malloc' function
        self.malloc_fn_ptr = self.configure_boehm_once()
        self._setup_str()
        self._make_functions()

    def _make_functions(self):

        def malloc_fixedsize(size):
            return self.malloc_fn_ptr(size)
        self.generate_function('malloc_fixedsize', malloc_fixedsize,
                               [lltype.Signed])

        def malloc_array(basesize, num_elem, itemsize, ofs_length):
            try:
                totalsize = ovfcheck(basesize + ovfcheck(itemsize * num_elem))
            except OverflowError:
                return lltype.nullptr(llmemory.GCREF.TO)
            res = self.malloc_fn_ptr(totalsize)
            if res:
                arrayptr = rffi.cast(rffi.CArrayPtr(lltype.Signed), res)
                arrayptr[ofs_length/WORD] = num_elem
            return res
        self.generate_function('malloc_array', malloc_array,
                               [lltype.Signed] * 4)

    def _bh_malloc(self, sizedescr):
        return self.malloc_fixedsize(sizedescr.size)

    def _bh_malloc_array(self, num_elem, arraydescr):
        return self.malloc_array(arraydescr.basesize, num_elem,
                                 arraydescr.itemsize,
                                 arraydescr.lendescr.offset)


# ____________________________________________________________
# All code below is for the hybrid or minimark GC


class GcRootMap_asmgcc(object):
    """Handles locating the stack roots in the assembler.
    This is the class supporting --gcrootfinder=asmgcc.
    """
    is_shadow_stack = False
    is_64_bit = (WORD == 8)

    LOC_REG       = 0
    LOC_ESP_PLUS  = 1
    LOC_EBP_PLUS  = 2
    LOC_EBP_MINUS = 3

    GCMAP_ARRAY = rffi.CArray(lltype.Signed)
    CALLSHAPE_ARRAY_PTR = rffi.CArrayPtr(rffi.UCHAR)

    def __init__(self, gcdescr=None):
        # '_gcmap' is an array of length '_gcmap_maxlength' of addresses.
        # '_gcmap_curlength' tells how full the array really is.
        # The addresses are actually grouped in pairs:
        #     (addr-after-the-CALL-in-assembler, addr-of-the-call-shape).
        # '_gcmap_deadentries' counts pairs marked dead (2nd item is NULL).
        # '_gcmap_sorted' is True only if we know the array is sorted.
        self._gcmap = lltype.nullptr(self.GCMAP_ARRAY)
        self._gcmap_curlength = 0
        self._gcmap_maxlength = 0
        self._gcmap_deadentries = 0
        self._gcmap_sorted = True

    def add_jit2gc_hooks(self, jit2gc):
        jit2gc.update({
            'gcmapstart': lambda: self.gcmapstart(),
            'gcmapend': lambda: self.gcmapend(),
            'gcmarksorted': lambda: self.gcmarksorted(),
            })

    def initialize(self):
        # hack hack hack.  Remove these lines and see MissingRTypeAttribute
        # when the rtyper tries to annotate these methods only when GC-ing...
        self.gcmapstart()
        self.gcmapend()
        self.gcmarksorted()

    def gcmapstart(self):
        return rffi.cast(llmemory.Address, self._gcmap)

    def gcmapend(self):
        addr = self.gcmapstart()
        if self._gcmap_curlength:
            addr += rffi.sizeof(lltype.Signed) * self._gcmap_curlength
            if not we_are_translated() and type(addr) is long:
                from rpython.rtyper.lltypesystem import ll2ctypes
                addr = ll2ctypes._lladdress(addr)       # XXX workaround
        return addr

    def gcmarksorted(self):
        # Called by the GC when it is about to sort [gcmapstart():gcmapend()].
        # Returns the previous sortedness flag -- i.e. returns True if it
        # is already sorted, False if sorting is needed.
        sorted = self._gcmap_sorted
        self._gcmap_sorted = True
        return sorted

    def put(self, retaddr, callshapeaddr):
        """'retaddr' is the address just after the CALL.
        'callshapeaddr' is the address of the raw 'shape' marker.
        Both addresses are actually integers here."""
        index = self._gcmap_curlength
        if index + 2 > self._gcmap_maxlength:
            index = self._enlarge_gcmap()
        self._gcmap[index] = retaddr
        self._gcmap[index+1] = callshapeaddr
        self._gcmap_curlength = index + 2
        self._gcmap_sorted = False

    @rgc.no_collect
    def _enlarge_gcmap(self):
        oldgcmap = self._gcmap
        if self._gcmap_deadentries * 3 * 2 > self._gcmap_maxlength:
            # More than 1/3rd of the entries are dead.  Don't actually
            # enlarge the gcmap table, but just clean up the dead entries.
            newgcmap = oldgcmap
        else:
            # Normal path: enlarge the array.
            newlength = 250 + (self._gcmap_maxlength // 3) * 4
            newgcmap = lltype.malloc(self.GCMAP_ARRAY, newlength, flavor='raw',
                                     track_allocation=False)
            self._gcmap_maxlength = newlength
        #
        j = 0
        i = 0
        end = self._gcmap_curlength
        while i < end:
            if oldgcmap[i + 1]:
                newgcmap[j] = oldgcmap[i]
                newgcmap[j + 1] = oldgcmap[i + 1]
                j += 2
            i += 2
        self._gcmap_curlength = j
        self._gcmap_deadentries = 0
        if oldgcmap != newgcmap:
            self._gcmap = newgcmap
            if oldgcmap:
                lltype.free(oldgcmap, flavor='raw', track_allocation=False)
        return j

    @rgc.no_collect
    def freeing_block(self, start, stop):
        # if [start:stop] is a raw block of assembler, then look up the
        # corresponding gcroot markers, and mark them as freed now in
        # self._gcmap by setting the 2nd address of every entry to NULL.
        gcmapstart = self.gcmapstart()
        gcmapend   = self.gcmapend()
        if gcmapstart == gcmapend:
            return
        if not self.gcmarksorted():
            asmgcroot.sort_gcmap(gcmapstart, gcmapend)
        # A note about gcmarksorted(): the deletion we do here keeps the
        # array sorted.  This avoids needing too many sort_gcmap()s.
        # Indeed, freeing_block() is typically called many times in a row,
        # so it will call sort_gcmap() at most the first time.
        startaddr = rffi.cast(llmemory.Address, start)
        stopaddr  = rffi.cast(llmemory.Address, stop)
        item = asmgcroot.binary_search(gcmapstart, gcmapend, startaddr)
        # 'item' points to one of the entries.  Because the whole array
        # is sorted, we know that it points either to the first entry we
        # want to kill, or to the previous entry.
        if item.address[0] < startaddr:
            item += asmgcroot.arrayitemsize    # go forward one entry
            assert item == gcmapend or item.address[0] >= startaddr
        while item != gcmapend and item.address[0] < stopaddr:
            item.address[1] = llmemory.NULL
            self._gcmap_deadentries += 1
            item += asmgcroot.arrayitemsize

    def get_basic_shape(self):
        # XXX: Should this code even really know about stack frame layout of
        # the JIT?
        if self.is_64_bit:
            return [chr(self.LOC_EBP_PLUS  | 4),    # return addr: at   8(%rbp)
                    chr(self.LOC_EBP_MINUS | 4),    # saved %rbx:  at  -8(%rbp)
                    chr(self.LOC_EBP_MINUS | 8),    # saved %r12:  at -16(%rbp)
                    chr(self.LOC_EBP_MINUS | 12),   # saved %r13:  at -24(%rbp)
                    chr(self.LOC_EBP_MINUS | 16),   # saved %r14:  at -32(%rbp)
                    chr(self.LOC_EBP_MINUS | 20),   # saved %r15:  at -40(%rbp)
                    chr(self.LOC_EBP_PLUS  | 0),    # saved %rbp:  at    (%rbp)
                    chr(0)]
        else:
            return [chr(self.LOC_EBP_PLUS  | 4),    # return addr: at   4(%ebp)
                    chr(self.LOC_EBP_MINUS | 4),    # saved %ebx:  at  -4(%ebp)
                    chr(self.LOC_EBP_MINUS | 8),    # saved %esi:  at  -8(%ebp)
                    chr(self.LOC_EBP_MINUS | 12),   # saved %edi:  at -12(%ebp)
                    chr(self.LOC_EBP_PLUS  | 0),    # saved %ebp:  at    (%ebp)
                    chr(0)]

    def _encode_num(self, shape, number):
        assert number >= 0
        flag = 0
        while number >= 0x80:
            shape.append(chr((number & 0x7F) | flag))
            flag = 0x80
            number >>= 7
        shape.append(chr(number | flag))

    def add_frame_offset(self, shape, offset):
        if self.is_64_bit:
            assert (offset & 7) == 0
            offset >>= 1
        else:
            assert (offset & 3) == 0
        if offset >= 0:
            num = self.LOC_EBP_PLUS | offset
        else:
            num = self.LOC_EBP_MINUS | (-offset)
        self._encode_num(shape, num)

    def add_callee_save_reg(self, shape, reg_index):
        assert reg_index > 0
        shape.append(chr(self.LOC_REG | (reg_index << 2)))

    def compress_callshape(self, shape, datablockwrapper):
        # Similar to compress_callshape() in trackgcroot.py.
        # Returns an address to raw memory (as an integer).
        length = len(shape)
        rawaddr = datablockwrapper.malloc_aligned(length, 1)
        p = rffi.cast(self.CALLSHAPE_ARRAY_PTR, rawaddr)
        for i in range(length):
            p[length-1-i] = rffi.cast(rffi.UCHAR, shape[i])
        return rawaddr


class GcRootMap_shadowstack(object):
    """Handles locating the stack roots in the assembler.
    This is the class supporting --gcrootfinder=shadowstack.
    """
    is_shadow_stack = True
    MARKER_FRAME = 8       # this marker now *follows* the frame addr

    # The "shadowstack" is a portable way in which the GC finds the
    # roots that live in the stack.  Normally it is just a list of
    # pointers to GC objects.  The pointers may be moved around by a GC
    # collection.  But with the JIT, an entry can also be MARKER_FRAME,
    # in which case the previous entry points to an assembler stack frame.
    # During a residual CALL from the assembler (which may indirectly
    # call the GC), we use the force_index stored in the assembler
    # stack frame to identify the call: we can go from the force_index
    # to a list of where the GC pointers are in the frame (this is the
    # purpose of the present class).
    #
    # Note that across CALL_MAY_FORCE or CALL_ASSEMBLER, we can also go
    # from the force_index to a ResumeGuardForcedDescr instance, which
    # is used if the virtualizable or the virtualrefs need to be forced
    # (see rpython.jit.backend.model).  The force_index number in the stack
    # frame is initially set to a non-negative value x, but it is
    # occasionally turned into (~x) in case of forcing.

    INTARRAYPTR = rffi.CArrayPtr(rffi.INT)
    CALLSHAPES_ARRAY = rffi.CArray(INTARRAYPTR)

    def __init__(self, gcdescr):
        self._callshapes = lltype.nullptr(self.CALLSHAPES_ARRAY)
        self._callshapes_maxlength = 0
        self.force_index_ofs = gcdescr.force_index_ofs

    def add_jit2gc_hooks(self, jit2gc):
        #
        # ---------------
        # This is used to enumerate the shadowstack in the presence
        # of the JIT.  It is also used by the stacklet support in
        # rlib/_stacklet_shadowstack.  That's why it is written as
        # an iterator that can also be used with a custom_trace.
        #
        class RootIterator:
            _alloc_flavor_ = "raw"

            def setcontext(iself, context):
                iself.context = context

            def nextleft(iself, gc, range_lowest, prev):
                # Return the next valid GC object's address, in right-to-left
                # order from the shadowstack array.  This usually means just
                # returning "prev - sizeofaddr", until we reach "range_lowest",
                # except that we are skipping NULLs.  If "prev - sizeofaddr"
                # contains a MARKER_FRAME instead, then we go into
                # JIT-frame-lookup mode.
                #
                while True:
                    #
                    # If we are not iterating right now in a JIT frame
                    if iself.frame_addr == 0:
                        #
                        # Look for the next shadowstack address that
                        # contains a valid pointer
                        while prev != range_lowest:
                            prev -= llmemory.sizeof(llmemory.Address)
                            if prev.signed[0] == self.MARKER_FRAME:
                                break
                            if gc.points_to_valid_gc_object(prev):
                                return prev
                        else:
                            return llmemory.NULL     # done
                        #
                        # It's a JIT frame.  Save away 'prev' for later, and
                        # go into JIT-frame-exploring mode.
                        prev -= llmemory.sizeof(llmemory.Address)
                        frame_addr = prev.signed[0]
                        iself.saved_prev = prev
                        iself.frame_addr = frame_addr
                        addr = llmemory.cast_int_to_adr(frame_addr +
                                                        self.force_index_ofs)
                        addr = iself.translateptr(iself.context, addr)
                        force_index = addr.signed[0]
                        if force_index < 0:
                            force_index = ~force_index
                        # NB: the next line reads a still-alive _callshapes,
                        # because we ensure that just before we called this
                        # piece of assembler, we put on the (same) stack a
                        # pointer to a loop_token that keeps the force_index
                        # alive.
                        callshape = self._callshapes[force_index]
                    else:
                        # Continuing to explore this JIT frame
                        callshape = iself.callshape
                    #
                    # 'callshape' points to the next INT of the callshape.
                    # If it's zero we are done with the JIT frame.
                    while rffi.cast(lltype.Signed, callshape[0]) != 0:
                        #
                        # Non-zero: it's an offset inside the JIT frame.
                        # Read it and increment 'callshape'.
                        offset = rffi.cast(lltype.Signed, callshape[0])
                        callshape = lltype.direct_ptradd(callshape, 1)
                        addr = llmemory.cast_int_to_adr(iself.frame_addr +
                                                        offset)
                        addr = iself.translateptr(iself.context, addr)
                        if gc.points_to_valid_gc_object(addr):
                            #
                            # The JIT frame contains a valid GC pointer at
                            # this address (as opposed to NULL).  Save
                            # 'callshape' for the next call, and return the
                            # address.
                            iself.callshape = callshape
                            return addr
                    #
                    # Restore 'prev' and loop back to the start.
                    iself.frame_addr = 0
                    prev = iself.saved_prev

        # ---------------
        #
        root_iterator = RootIterator()
        root_iterator.frame_addr = 0
        root_iterator.context = llmemory.NULL
        root_iterator.translateptr = lambda context, addr: addr
        jit2gc.update({
            'root_iterator': root_iterator,
            })

    def initialize(self):
        pass

    def get_basic_shape(self):
        return []

    def add_frame_offset(self, shape, offset):
        assert offset != 0
        shape.append(offset)

    def add_callee_save_reg(self, shape, register):
        msg = "GC pointer in %s was not spilled" % register
        os.write(2, '[llsupport/gc] %s\n' % msg)
        raise AssertionError(msg)

    def compress_callshape(self, shape, datablockwrapper):
        length = len(shape)
        SZINT = rffi.sizeof(rffi.INT)
        rawaddr = datablockwrapper.malloc_aligned((length + 1) * SZINT, SZINT)
        p = rffi.cast(self.INTARRAYPTR, rawaddr)
        for i in range(length):
            p[i] = rffi.cast(rffi.INT, shape[i])
        p[length] = rffi.cast(rffi.INT, 0)
        return p

    def write_callshape(self, p, force_index):
        if force_index >= self._callshapes_maxlength:
            self._enlarge_callshape_list(force_index + 1)
        self._callshapes[force_index] = p

    def _enlarge_callshape_list(self, minsize):
        newlength = 250 + (self._callshapes_maxlength // 3) * 4
        if newlength < minsize:
            newlength = minsize
        newarray = lltype.malloc(self.CALLSHAPES_ARRAY, newlength,
                                 flavor='raw', track_allocation=False)
        if self._callshapes:
            i = self._callshapes_maxlength - 1
            while i >= 0:
                newarray[i] = self._callshapes[i]
                i -= 1
            lltype.free(self._callshapes, flavor='raw', track_allocation=False)
        self._callshapes = newarray
        self._callshapes_maxlength = newlength

    def freeing_block(self, start, stop):
        pass     # nothing needed here

    def get_root_stack_top_addr(self):
        rst_addr = llop.gc_adr_of_root_stack_top(llmemory.Address)
        return rffi.cast(lltype.Signed, rst_addr)


class WriteBarrierDescr(AbstractDescr):
    def __init__(self, gc_ll_descr):
        self.llop1 = gc_ll_descr.llop1
        self.WB_FUNCPTR = gc_ll_descr.WB_FUNCPTR
        self.fielddescr_tid = gc_ll_descr.fielddescr_tid
        #
        GCClass = gc_ll_descr.GCClass
        if GCClass is None:     # for tests
            return
        self.jit_wb_if_flag = GCClass.JIT_WB_IF_FLAG
        self.jit_wb_if_flag_byteofs, self.jit_wb_if_flag_singlebyte = (
            self.extract_flag_byte(self.jit_wb_if_flag))
        #
        if hasattr(GCClass, 'JIT_WB_CARDS_SET'):
            self.jit_wb_cards_set = GCClass.JIT_WB_CARDS_SET
            self.jit_wb_card_page_shift = GCClass.JIT_WB_CARD_PAGE_SHIFT
            self.jit_wb_cards_set_byteofs, self.jit_wb_cards_set_singlebyte = (
                self.extract_flag_byte(self.jit_wb_cards_set))
            #
            # the x86 backend uses the following "accidental" facts to
            # avoid one instruction:
            assert self.jit_wb_cards_set_byteofs == self.jit_wb_if_flag_byteofs
            assert self.jit_wb_cards_set_singlebyte == -0x80
        else:
            self.jit_wb_cards_set = 0

    def extract_flag_byte(self, flag_word):
        # if convenient for the backend, we compute the info about
        # the flag as (byte-offset, single-byte-flag).
        import struct
        value = struct.pack(lltype.SignedFmt, flag_word)
        assert value.count('\x00') == len(value) - 1    # only one byte is != 0
        i = 0
        while value[i] == '\x00': i += 1
        return (i, struct.unpack('b', value[i])[0])

    def get_write_barrier_fn(self, cpu):
        llop1 = self.llop1
        funcptr = llop1.get_write_barrier_failing_case(self.WB_FUNCPTR)
        funcaddr = llmemory.cast_ptr_to_adr(funcptr)
        return cpu.cast_adr_to_int(funcaddr)

    def get_write_barrier_from_array_fn(self, cpu):
        # returns a function with arguments [array, index, newvalue]
        llop1 = self.llop1
        funcptr = llop1.get_write_barrier_from_array_failing_case(
            self.WB_FUNCPTR)
        funcaddr = llmemory.cast_ptr_to_adr(funcptr)
        return cpu.cast_adr_to_int(funcaddr)    # this may return 0

    def has_write_barrier_from_array(self, cpu):
        return self.get_write_barrier_from_array_fn(cpu) != 0


class GcLLDescr_framework(GcLLDescription):
    DEBUG = False    # forced to True by x86/test/test_zrpy_gc.py
    kind = 'framework'
    round_up = True

    def __init__(self, gcdescr, translator, rtyper, llop1=llop,
                 really_not_translated=False):
        GcLLDescription.__init__(self, gcdescr, translator, rtyper)
        self.translator = translator
        self.llop1 = llop1
        if really_not_translated:
            assert not self.translate_support_code  # but half does not work
            self._initialize_for_tests()
        else:
            assert self.translate_support_code,"required with the framework GC"
            self._check_valid_gc()
            self._make_gcrootmap()
            self._make_layoutbuilder()
            self._setup_gcclass()
            self._setup_tid()
        self._setup_write_barrier()
        self._setup_str()
        self._make_functions(really_not_translated)

    def _initialize_for_tests(self):
        self.layoutbuilder = None
        self.fielddescr_tid = AbstractDescr()
        self.max_size_of_young_obj = 1000
        self.GCClass = None

    def _check_valid_gc(self):
        # we need the hybrid or minimark GC for rgc._make_sure_does_not_move()
        # to work.  Additionally, 'hybrid' is missing some stuff like
        # jit_remember_young_pointer() for now.
        if self.gcdescr.config.translation.gc not in ('minimark',):
            raise NotImplementedError("--gc=%s not implemented with the JIT" %
                                      (self.gcdescr.config.translation.gc,))

    def _make_gcrootmap(self):
        # to find roots in the assembler, make a GcRootMap
        name = self.gcdescr.config.translation.gcrootfinder
        try:
            cls = globals()['GcRootMap_' + name]
        except KeyError:
            raise NotImplementedError("--gcrootfinder=%s not implemented"
                                      " with the JIT" % (name,))
        gcrootmap = cls(self.gcdescr)
        self.gcrootmap = gcrootmap

    def _make_layoutbuilder(self):
        # make a TransformerLayoutBuilder and save it on the translator
        # where it can be fished and reused by the FrameworkGCTransformer
        from rpython.rtyper.memory.gctransform import framework
        translator = self.translator
        self.layoutbuilder = framework.TransformerLayoutBuilder(translator)
        self.layoutbuilder.delay_encoding()
        translator._jit2gc = {'layoutbuilder': self.layoutbuilder}
        self.gcrootmap.add_jit2gc_hooks(translator._jit2gc)

    def _setup_gcclass(self):
        from rpython.rtyper.memory.gcheader import GCHeaderBuilder
        self.GCClass = self.layoutbuilder.GCClass
        self.moving_gc = self.GCClass.moving_gc
        self.HDRPTR = lltype.Ptr(self.GCClass.HDR)
        self.gcheaderbuilder = GCHeaderBuilder(self.HDRPTR.TO)
        self.max_size_of_young_obj = self.GCClass.JIT_max_size_of_young_obj()
        self.minimal_size_in_nursery=self.GCClass.JIT_minimal_size_in_nursery()

        # for the fast path of mallocs, the following must be true, at least
        assert self.GCClass.inline_simple_malloc
        assert self.GCClass.inline_simple_malloc_varsize

    def _setup_tid(self):
        self.fielddescr_tid = get_field_descr(self, self.GCClass.HDR, 'tid')

    def _setup_write_barrier(self):
        self.WB_FUNCPTR = lltype.Ptr(lltype.FuncType(
            [llmemory.Address], lltype.Void))
        self.write_barrier_descr = WriteBarrierDescr(self)

    def _make_functions(self, really_not_translated):
        from rpython.rtyper.memory.gctypelayout import check_typeid
        llop1 = self.llop1
        (self.standard_array_basesize, _, self.standard_array_length_ofs) = \
             symbolic.get_array_token(lltype.GcArray(lltype.Signed),
                                      not really_not_translated)

        def malloc_nursery_slowpath(size):
            """Allocate 'size' null bytes out of the nursery.
            Note that the fast path is typically inlined by the backend."""
            assert size >= self.minimal_size_in_nursery
            if self.DEBUG:
                self._random_usage_of_xmm_registers()
            type_id = rffi.cast(llgroup.HALFWORD, 0)    # missing here
            return llop1.do_malloc_fixedsize_clear(llmemory.GCREF,
                                                   type_id, size,
                                                   False, False, False)
        self.generate_function('malloc_nursery', malloc_nursery_slowpath,
                               [lltype.Signed])

        def malloc_array(itemsize, tid, num_elem):
            """Allocate an array with a variable-size num_elem.
            Only works for standard arrays."""
            assert num_elem >= 0, 'num_elem should be >= 0'
            type_id = llop.extract_ushort(llgroup.HALFWORD, tid)
            check_typeid(type_id)
            return llop1.do_malloc_varsize_clear(
                llmemory.GCREF,
                type_id, num_elem, self.standard_array_basesize, itemsize,
                self.standard_array_length_ofs)
        self.generate_function('malloc_array', malloc_array,
                               [lltype.Signed] * 3)

        def malloc_array_nonstandard(basesize, itemsize, lengthofs, tid,
                                     num_elem):
            """For the rare case of non-standard arrays, i.e. arrays where
            self.standard_array_{basesize,length_ofs} is wrong.  It can
            occur e.g. with arrays of floats on Win32."""
            type_id = llop.extract_ushort(llgroup.HALFWORD, tid)
            check_typeid(type_id)
            return llop1.do_malloc_varsize_clear(
                llmemory.GCREF,
                type_id, num_elem, basesize, itemsize, lengthofs)
        self.generate_function('malloc_array_nonstandard',
                               malloc_array_nonstandard,
                               [lltype.Signed] * 5)

        str_type_id    = self.str_descr.tid
        str_basesize   = self.str_descr.basesize
        str_itemsize   = self.str_descr.itemsize
        str_ofs_length = self.str_descr.lendescr.offset
        unicode_type_id    = self.unicode_descr.tid
        unicode_basesize   = self.unicode_descr.basesize
        unicode_itemsize   = self.unicode_descr.itemsize
        unicode_ofs_length = self.unicode_descr.lendescr.offset

        def malloc_str(length):
            return llop1.do_malloc_varsize_clear(
                llmemory.GCREF,
                str_type_id, length, str_basesize, str_itemsize,
                str_ofs_length)
        self.generate_function('malloc_str', malloc_str,
                               [lltype.Signed])

        def malloc_unicode(length):
            return llop1.do_malloc_varsize_clear(
                llmemory.GCREF,
                unicode_type_id, length, unicode_basesize, unicode_itemsize,
                unicode_ofs_length)
        self.generate_function('malloc_unicode', malloc_unicode,
                               [lltype.Signed])

        # Never called as far as I can tell, but there for completeness:
        # allocate a fixed-size object, but not in the nursery, because
        # it is too big.
        def malloc_big_fixedsize(size, tid):
            if self.DEBUG:
                self._random_usage_of_xmm_registers()
            type_id = llop.extract_ushort(llgroup.HALFWORD, tid)
            check_typeid(type_id)
            return llop1.do_malloc_fixedsize_clear(llmemory.GCREF,
                                                   type_id, size,
                                                   False, False, False)
        self.generate_function('malloc_big_fixedsize', malloc_big_fixedsize,
                               [lltype.Signed] * 2)

    def _bh_malloc(self, sizedescr):
        from rpython.rtyper.memory.gctypelayout import check_typeid
        llop1 = self.llop1
        type_id = llop.extract_ushort(llgroup.HALFWORD, sizedescr.tid)
        check_typeid(type_id)
        return llop1.do_malloc_fixedsize_clear(llmemory.GCREF,
                                               type_id, sizedescr.size,
                                               False, False, False)

    def _bh_malloc_array(self, num_elem, arraydescr):
        from rpython.rtyper.memory.gctypelayout import check_typeid
        llop1 = self.llop1
        type_id = llop.extract_ushort(llgroup.HALFWORD, arraydescr.tid)
        check_typeid(type_id)
        return llop1.do_malloc_varsize_clear(llmemory.GCREF,
                                             type_id, num_elem,
                                             arraydescr.basesize,
                                             arraydescr.itemsize,
                                             arraydescr.lendescr.offset)


    class ForTestOnly:
        pass
    for_test_only = ForTestOnly()
    for_test_only.x = 1.23

    def _random_usage_of_xmm_registers(self):
        x0 = self.for_test_only.x
        x1 = x0 * 0.1
        x2 = x0 * 0.2
        x3 = x0 * 0.3
        self.for_test_only.x = x0 + x1 + x2 + x3

    def get_nursery_free_addr(self):
        nurs_addr = llop.gc_adr_of_nursery_free(llmemory.Address)
        return rffi.cast(lltype.Signed, nurs_addr)

    def get_nursery_top_addr(self):
        nurs_top_addr = llop.gc_adr_of_nursery_top(llmemory.Address)
        return rffi.cast(lltype.Signed, nurs_top_addr)

    def initialize(self):
        self.gcrootmap.initialize()

    def init_size_descr(self, S, descr):
        if self.layoutbuilder is not None:
            type_id = self.layoutbuilder.get_type_id(S)
            assert not self.layoutbuilder.is_weakref_type(S)
            assert not self.layoutbuilder.has_finalizer(S)
            descr.tid = llop.combine_ushort(lltype.Signed, type_id, 0)

    def init_array_descr(self, A, descr):
        if self.layoutbuilder is not None:
            type_id = self.layoutbuilder.get_type_id(A)
            descr.tid = llop.combine_ushort(lltype.Signed, type_id, 0)

    def _set_tid(self, gcptr, tid):
        hdr_addr = llmemory.cast_ptr_to_adr(gcptr)
        hdr_addr -= self.gcheaderbuilder.size_gc_header
        hdr = llmemory.cast_adr_to_ptr(hdr_addr, self.HDRPTR)
        hdr.tid = tid

    def do_write_barrier(self, gcref_struct, gcref_newptr):
        hdr_addr = llmemory.cast_ptr_to_adr(gcref_struct)
        hdr_addr -= self.gcheaderbuilder.size_gc_header
        hdr = llmemory.cast_adr_to_ptr(hdr_addr, self.HDRPTR)
        if hdr.tid & self.GCClass.JIT_WB_IF_FLAG:
            # get a pointer to the 'remember_young_pointer' function from
            # the GC, and call it immediately
            llop1 = self.llop1
            funcptr = llop1.get_write_barrier_failing_case(self.WB_FUNCPTR)
            funcptr(llmemory.cast_ptr_to_adr(gcref_struct))

    def can_use_nursery_malloc(self, size):
        return size < self.max_size_of_young_obj

    def has_write_barrier_class(self):
        return WriteBarrierDescr

    def freeing_block(self, start, stop):
        self.gcrootmap.freeing_block(start, stop)

    def get_malloc_slowpath_addr(self):
        return self.get_malloc_fn_addr('malloc_nursery')

# ____________________________________________________________

def get_ll_description(gcdescr, translator=None, rtyper=None):
    # translator is None if translate_support_code is False.
    if gcdescr is not None:
        name = gcdescr.config.translation.gctransformer
    else:
        name = "boehm"
    try:
        cls = globals()['GcLLDescr_' + name]
    except KeyError:
        raise NotImplementedError("GC transformer %r not supported by "
                                  "the JIT backend" % (name,))
    return cls(gcdescr, translator, rtyper)
