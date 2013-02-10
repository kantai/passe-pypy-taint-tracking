# Helper to build the lowleveltype corresponding to an RPython tuple.
# This is not in rtuple.py so that it can be imported without bringing
# the whole rtyper in.

from rpython.rtyper.lltypesystem.lltype import Void, Ptr, GcStruct


def TUPLE_TYPE(field_lltypes):
    if len(field_lltypes) == 0:
        return Void      # empty tuple
    else:
        fields = [('item%d' % i, TYPE) for i, TYPE in enumerate(field_lltypes)]
        kwds = {'hints': {'immutable': True,
                          'noidentity': True}}
        return Ptr(GcStruct('tuple%d' % len(field_lltypes), *fields, **kwds))
