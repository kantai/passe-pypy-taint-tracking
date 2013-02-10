from pypy.interpreter.baseobjspace import Wrappable
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.typedef import TypeDef, interp_attrproperty
from pypy.interpreter.typedef import GetSetProperty
from pypy.interpreter.gateway import interp2app


QUOTE_MINIMAL, QUOTE_ALL, QUOTE_NONNUMERIC, QUOTE_NONE = range(4)


class W_Dialect(Wrappable):
    _immutable_fields_ = [
        "dialect",
        "delimiter",
        "doublequote",
        "escapechar",
        "lineterminator",
        "quotechar",
        "quoting",
        "skipinitialspace",
        "strict",
        ]

def _fetch(space, w_dialect, name):
    return space.findattr(w_dialect, space.wrap(name))

def _get_bool(space, w_src, default):
    if w_src is None:
        return default
    return space.is_true(w_src)

def _get_int(space, w_src, default):
    if w_src is None:
        return default
    return space.int_w(w_src)

def _get_str(space, w_src, default):
    if w_src is None:
        return default
    return space.str_w(w_src)

def _get_char(space, w_src, default, name):
    if w_src is None:
        return default
    if space.is_w(w_src, space.w_None):
        return '\0'
    src = space.str_w(w_src)
    if len(src) == 1:
        return src[0]
    if len(src) == 0:
        return '\0'
    raise operationerrfmt(space.w_TypeError,
                          '"%s" must be a 1-character string', name)

def _build_dialect(space, w_dialect, w_delimiter, w_doublequote,
                   w_escapechar, w_lineterminator, w_quotechar, w_quoting,
                   w_skipinitialspace, w_strict):
    if w_dialect is not None:
        if space.isinstance_w(w_dialect, space.w_basestring):
            w_module = space.getbuiltinmodule('_csv')
            w_dialect = space.call_method(w_module, 'get_dialect', w_dialect)

        dialect = space.interpclass_w(w_dialect)
        if (isinstance(dialect, W_Dialect) and
            w_delimiter is None and
            w_doublequote is None and
            w_escapechar is None and
            w_lineterminator is None and
            w_quotechar is None and
            w_quoting is None and
            w_skipinitialspace is None and
            w_strict is None):
            return dialect

        if w_delimiter is None:
            w_delimiter = _fetch(space, w_dialect, 'delimiter')
        if w_doublequote is None:
            w_doublequote = _fetch(space, w_dialect, 'doublequote')
        if w_escapechar is None:
            w_escapechar = _fetch(space, w_dialect, 'escapechar')
        if w_lineterminator is None:
            w_lineterminator = _fetch(space, w_dialect, 'lineterminator')
        if w_quotechar is None:
            w_quotechar = _fetch(space, w_dialect, 'quotechar')
        if w_quoting is None:
            w_quoting = _fetch(space, w_dialect, 'quoting')
        if w_skipinitialspace is None:
            w_skipinitialspace = _fetch(space, w_dialect, 'skipinitialspace')
        if w_strict is None:
            w_strict = _fetch(space, w_dialect, 'strict')

    dialect = W_Dialect()
    dialect.delimiter = _get_char(space, w_delimiter, ',', 'delimiter')
    dialect.doublequote = _get_bool(space, w_doublequote, True)
    dialect.escapechar = _get_char(space, w_escapechar, '\0', 'escapechar')
    dialect.lineterminator = _get_str(space, w_lineterminator, '\r\n')
    dialect.quotechar = _get_char(space, w_quotechar, '"', 'quotechar')
    tmp_quoting = _get_int(space, w_quoting, QUOTE_MINIMAL)
    dialect.skipinitialspace = _get_bool(space, w_skipinitialspace, False)
    dialect.strict = _get_bool(space, w_strict, False)

    # validate options
    if not (0 <= tmp_quoting < 4):
        raise OperationError(space.w_TypeError,
                             space.wrap('bad "quoting" value'))

    if dialect.delimiter == '\0':
        raise OperationError(space.w_TypeError,
                             space.wrap('delimiter must be set'))

    if space.is_w(w_quotechar, space.w_None) and w_quoting is None:
        tmp_quoting = QUOTE_NONE
    if tmp_quoting != QUOTE_NONE and dialect.quotechar == '\0':
        raise OperationError(space.w_TypeError,
                        space.wrap('quotechar must be set if quoting enabled'))
    dialect.quoting = tmp_quoting
    return dialect

def W_Dialect___new__(space, w_subtype, w_dialect = None,
                      w_delimiter        = None,
                      w_doublequote      = None,
                      w_escapechar       = None,
                      w_lineterminator   = None,
                      w_quotechar        = None,
                      w_quoting          = None,
                      w_skipinitialspace = None,
                      w_strict           = None,
                      ):
    dialect = _build_dialect(space, w_dialect, w_delimiter, w_doublequote,
                             w_escapechar, w_lineterminator, w_quotechar,
                             w_quoting, w_skipinitialspace, w_strict)
    if space.is_w(w_subtype, space.gettypeobject(W_Dialect.typedef)):
        return space.wrap(dialect)
    else:
        subdialect = space.allocate_instance(W_Dialect, w_subtype)
        subdialect.delimiter        = dialect.delimiter
        subdialect.doublequote      = dialect.doublequote
        subdialect.escapechar       = dialect.escapechar
        subdialect.lineterminator   = dialect.lineterminator
        subdialect.quotechar        = dialect.quotechar
        subdialect.quoting          = dialect.quoting
        subdialect.skipinitialspace = dialect.skipinitialspace
        subdialect.strict           = dialect.strict
        return space.wrap(subdialect)


def _get_escapechar(space, dialect):
    if dialect.escapechar == '\0':
        return space.w_None
    return space.wrap(dialect.escapechar)

def _get_quotechar(space, dialect):
    if dialect.quotechar == '\0':
        return space.w_None
    return space.wrap(dialect.quotechar)


W_Dialect.typedef = TypeDef(
        'Dialect',
        __module__ = '_csv',
        __new__ = interp2app(W_Dialect___new__),

        delimiter        = interp_attrproperty('delimiter', W_Dialect),
        doublequote      = interp_attrproperty('doublequote', W_Dialect),
        escapechar       = GetSetProperty(_get_escapechar, cls=W_Dialect),
        lineterminator   = interp_attrproperty('lineterminator', W_Dialect),
        quotechar        = GetSetProperty(_get_quotechar, cls=W_Dialect),
        quoting          = interp_attrproperty('quoting', W_Dialect),
        skipinitialspace = interp_attrproperty('skipinitialspace', W_Dialect),
        strict           = interp_attrproperty('strict', W_Dialect),

        __doc__ = """CSV dialect

The Dialect type records CSV parsing and generation options.
""")
