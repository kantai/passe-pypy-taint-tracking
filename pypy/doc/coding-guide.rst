====================================
Coding Guide
====================================

.. contents::

This document describes coding requirements and conventions for
working with the PyPy code base.  Please read it carefully and
ask back any questions you might have. The document does not talk
very much about coding style issues. We mostly follow `PEP 8`_ though.
If in doubt, follow the style that is already present in the code base.

.. _`PEP 8`: http://www.python.org/dev/peps/pep-0008/

.. _`RPython`:

Overview and motivation
========================

We are writing a Python interpreter in Python, using Python's well known
ability to step behind the algorithmic problems as a language. At first glance,
one might think this achieves nothing but a better understanding how the
interpreter works.  This alone would make it worth doing, but we have much
larger goals.


CPython vs. PyPy
-------------------

Compared to the CPython implementation, Python takes the role of the C
Code. We rewrite the CPython interpreter in Python itself.  We could
also aim at writing a more flexible interpreter at C level but we
want to use Python to give an alternative description of the interpreter.

The clear advantage is that such a description is shorter and simpler to
read, and many implementation details vanish. The drawback of this approach is
that this interpreter will be unbearably slow as long as it is run on top
of CPython.

To get to a useful interpreter again, we need to translate our
high-level description of Python to a lower level one.  One rather
straight-forward way is to do a whole program analysis of the PyPy
interpreter and create a C source, again. There are many other ways,
but let's stick with this somewhat canonical approach.


.. _`application-level`:
.. _`interpreter-level`:

Application-level and interpreter-level execution and objects
-------------------------------------------------------------

Since Python is used for implementing all of our code base, there is a
crucial distinction to be aware of: that between *interpreter-level* objects and 
*application-level* objects.  The latter are the ones that you deal with
when you write normal python programs.  Interpreter-level code, however,
cannot invoke operations nor access attributes from application-level
objects.  You will immediately recognize any interpreter level code in
PyPy, because half the variable and object names start with a ``w_``, which
indicates that they are `wrapped`_ application-level values. 

Let's show the difference with a simple example.  To sum the contents of
two variables ``a`` and ``b``, one would write the simple application-level
``a+b`` -- in contrast, the equivalent interpreter-level code is
``space.add(w_a, w_b)``, where ``space`` is an instance of an object space,
and ``w_a`` and ``w_b`` are typical names for the wrapped versions of the
two variables.

It helps to remember how CPython deals with the same issue: interpreter
level code, in CPython, is written in C and thus typical code for the
addition is ``PyNumber_Add(p_a, p_b)`` where ``p_a`` and ``p_b`` are C
variables of type ``PyObject*``. This is conceptually similar to how we write
our interpreter-level code in Python.

Moreover, in PyPy we have to make a sharp distinction between
interpreter- and application-level *exceptions*: application exceptions
are always contained inside an instance of ``OperationError``.  This
makes it easy to distinguish failures (or bugs) in our interpreter-level code
from failures appearing in a python application level program that we are
interpreting.


.. _`app-preferable`: 

Application level is often preferable 
-------------------------------------

Application-level code is substantially higher-level, and therefore
correspondingly easier to write and debug.  For example, suppose we want
to implement the ``update`` method of dict objects.  Programming at
application level, we can write an obvious, simple implementation, one
that looks like an **executable definition** of ``update``, for
example::

    def update(self, other):
        for k in other.keys():
            self[k] = other[k]

If we had to code only at interpreter level, we would have to code
something much lower-level and involved, say something like::

    def update(space, w_self, w_other):
        w_keys = space.call_method(w_other, 'keys')
        w_iter = space.iter(w_keys)
        while True:
            try:
                w_key = space.next(w_iter)
            except OperationError, e:
                if not e.match(space, space.w_StopIteration):
                    raise       # re-raise other app-level exceptions
                break
            w_value = space.getitem(w_other, w_key)
            space.setitem(w_self, w_key, w_value)

This interpreter-level implementation looks much more similar to the C
source code.  It is still more readable than its C counterpart because 
it doesn't contain memory management details and can use Python's native 
exception mechanism. 

In any case, it should be obvious that the application-level implementation 
is definitely more readable, more elegant and more maintainable than the
interpreter-level one (and indeed, dict.update is really implemented at
applevel in PyPy).

In fact, in almost all parts of PyPy, you find application level code in
the middle of interpreter-level code.  Apart from some bootstrapping
problems (application level functions need a certain initialization
level of the object space before they can be executed), application
level code is usually preferable.  We have an abstraction (called the
'Gateway') which allows the caller of a function to remain ignorant of
whether a particular function is implemented at application or
interpreter level. 

Our runtime interpreter is "RPython"
----------------------------------------------

In order to make a C code generator feasible all code on interpreter level has
to restrict itself to a subset of the Python language, and we adhere to some
rules which make translation to lower level languages feasible. Code on
application level can still use the full expressivity of Python.

Unlike source-to-source translations (like e.g. Starkiller_ or more recently
ShedSkin_) we start
translation from live python code objects which constitute our Python
interpreter.   When doing its work of interpreting bytecode our Python
implementation must behave in a static way often referenced as
"RPythonic".

.. _Starkiller: http://people.csail.mit.edu/jrb/Projects/starkiller.pdf
.. _ShedSkin: http://shed-skin.blogspot.com/

However, when the PyPy interpreter is started as a Python program, it
can use all of the Python language until it reaches a certain point in
time, from which on everything that is being executed must be static.
That is, during initialization our program is free to use the
full dynamism of Python, including dynamic code generation.

An example can be found in the current implementation which is quite
elegant: For the definition of all the opcodes of the Python
interpreter, the module ``dis`` is imported and used to initialize our
bytecode interpreter.  (See ``__initclass__`` in
`pypy/interpreter/pyopcode.py`_).  This
saves us from adding extra modules to PyPy. The import code is run at
startup time, and we are allowed to use the CPython builtin import
function.

After the startup code is finished, all resulting objects, functions,
code blocks etc. must adhere to certain runtime restrictions which we
describe further below.  Here is some background for why this is so:
during translation, a whole program analysis ("type inference") is
performed, which makes use of the restrictions defined in RPython. This
enables the code generator to emit efficient machine level replacements
for pure integer objects, for instance.

RPython
=================

RPython Definition
------------------

RPython is a restricted subset of Python that is amenable to static analysis.
Although there are additions to the language and some things might surprisingly
work, this is a rough list of restrictions that should be considered. Note
that there are tons of special cased restrictions that you'll encounter
as you go. The exact definition is "RPython is everything that our translation
toolchain can accept" :)

.. _`wrapped object`: coding-guide.html#wrapping-rules

Flow restrictions
-------------------------

**variables**

  variables should contain values of at most one type as described in
  `Object restrictions`_ at each control flow point, that means for
  example that joining control paths using the same variable to
  contain both a string and a int must be avoided.  It is allowed to
  mix None (basically with the role of a null pointer) with many other
  types: `wrapped objects`, class instances, lists, dicts, strings, etc.
  but *not* with int, floats or tuples.

**constants**

  all module globals are considered constants.  Their binding must not
  be changed at run-time.  Moreover, global (i.e. prebuilt) lists and
  dictionaries are supposed to be immutable: modifying e.g. a global
  list will give inconsistent results.  However, global instances don't
  have this restriction, so if you need mutable global state, store it
  in the attributes of some prebuilt singleton instance.



**control structures**

  all allowed, ``for`` loops restricted to builtin types, generators
  very restricted.

**range**

  ``range`` and ``xrange`` are identical. ``range`` does not necessarily create an array,
  only if the result is modified. It is allowed everywhere and completely
  implemented. The only visible difference to CPython is the inaccessibility
  of the ``xrange`` fields start, stop and step.

**definitions**

  run-time definition of classes or functions is not allowed.

**generators**

  generators are supported, but their exact scope is very limited. you can't
  merge two different generator in one control point.

**exceptions**

+ fully supported
+ see below `Exception rules`_ for restrictions on exceptions raised by built-in operations


Object restrictions
-------------------------

We are using

**integer, float, boolean**

  works.

**strings**

  a lot of, but not all string methods are supported and those that are
  supported, not necesarilly accept all arguments.  Indexes can be
  negative.  In case they are not, then you get slightly more efficient
  code if the translator can prove that they are non-negative.  When
  slicing a string it is necessary to prove that the slice start and
  stop indexes are non-negative. There is no implicit str-to-unicode cast
  anywhere. Simple string formatting using the ``%`` operator works, as long
  as the format string is known at translation time; the only supported
  formatting specifiers are ``%s``, ``%d``, ``%x``, ``%o``, ``%f``, plus
  ``%r`` but only for user-defined instances. Modifiers such as conversion
  flags, precision, length etc. are not supported. Moreover, it is forbidden
  to mix unicode and strings when formatting.

**tuples**

  no variable-length tuples; use them to store or return pairs or n-tuples of
  values. Each combination of types for elements and length constitute
  a separate and not mixable type.

**lists**

  lists are used as an allocated array.  Lists are over-allocated, so list.append()
  is reasonably fast. However, if you use a fixed-size list, the code
  is more efficient. Annotator can figure out most of the time that your
  list is fixed-size, even when you use list comprehension.
  Negative or out-of-bound indexes are only allowed for the
  most common operations, as follows:

  - *indexing*:
    positive and negative indexes are allowed. Indexes are checked when requested
    by an IndexError exception clause.
  
  - *slicing*:
    the slice start must be within bounds. The stop doesn't need to, but it must
    not be smaller than the start.  All negative indexes are disallowed, except for
    the [:-1] special case.  No step.  Slice deletion follows the same rules.
    
  - *slice assignment*:
    only supports ``lst[x:y] = sublist``, if ``len(sublist) == y - x``.
    In other words, slice assignment cannot change the total length of the list,
    but just replace items.

  - *other operators*:
    ``+``, ``+=``, ``in``, ``*``, ``*=``, ``==``, ``!=`` work as expected.

  - *methods*:
    append, index, insert, extend, reverse, pop.  The index used in pop() follows
    the same rules as for *indexing* above.  The index used in insert() must be within
    bounds and not negative.

**dicts**

  dicts with a unique key type only, provided it is hashable. Custom
  hash functions and custom equality will not be honored.
  Use ``pypy.rlib.objectmodel.r_dict`` for custom hash functions.


**list comprehensions**

  May be used to create allocated, initialized arrays.

**functions**

+ statically called functions may use defaults and a variable number of
  arguments (which may be passed as a list instead of a tuple, so write code
  that does not depend on it being a tuple).

+ dynamic dispatch enforces the use of signatures that are equal for all
  possible called function, or at least "compatible enough".  This
  concerns mainly method calls, when the method is overridden or in any
  way given different definitions in different classes.  It also concerns
  the less common case of explicitly manipulated function objects.
  Describing the exact compatibility rules is rather involved (but if you
  break them, you should get explicit errors from the rtyper and not
  obscure crashes.)

**builtin functions**

  A number of builtin functions can be used.  The precise set can be
  found in `pypy/annotation/builtin.py`_ (see ``def builtin_xxx()``).
  Some builtin functions may be limited in what they support, though.

  ``int, float, str, ord, chr``... are available as simple conversion
  functions.  Note that ``int, float, str``... have a special meaning as
  a type inside of isinstance only.

**classes**

+ methods and other class attributes do not change after startup
+ single inheritance is fully supported
+ simple mixins work too, but the mixed in class needs a ``_mixin_ = True``
  class attribute

+ classes are first-class objects too

**objects**

  Normal rules apply. Special methods are not honoured, except ``__init__``,
  ``__del__`` and ``__iter__``.

This layout makes the number of types to take care about quite limited.


Integer Types
-------------------------

While implementing the integer type, we stumbled over the problem that
integers are quite in flux in CPython right now. Starting with Python 2.4,
integers mutate into longs on overflow.  In contrast, we need
a way to perform wrap-around machine-sized arithmetic by default, while still
being able to check for overflow when we need it explicitly.  Moreover, we need
a consistent behavior before and after translation.

We use normal integers for signed arithmetic.  It means that before
translation we get longs in case of overflow, and after translation we get a
silent wrap-around.  Whenever we need more control, we use the following
helpers (which live the `pypy/rlib/rarithmetic.py`_):

**ovfcheck()**

  This special function should only be used with a single arithmetic operation
  as its argument, e.g. ``z = ovfcheck(x+y)``.  Its intended meaning is to
  perform the given operation in overflow-checking mode.

  At run-time, in Python, the ovfcheck() function itself checks the result
  and raises OverflowError if it is a ``long``.  But the code generators use
  ovfcheck() as a hint: they replace the whole ``ovfcheck(x+y)`` expression
  with a single overflow-checking addition in C.

**intmask()**

  This function is used for wrap-around arithmetic.  It returns the lower bits
  of its argument, masking away anything that doesn't fit in a C "signed long int".
  Its purpose is, in Python, to convert from a Python ``long`` that resulted from a
  previous operation back to a Python ``int``.  The code generators ignore
  intmask() entirely, as they are doing wrap-around signed arithmetic all the time
  by default anyway.  (We have no equivalent of the "int" versus "long int"
  distinction of C at the moment and assume "long ints" everywhere.)

**r_uint**

  In a few cases (e.g. hash table manipulation), we need machine-sized unsigned
  arithmetic.  For these cases there is the r_uint class, which is a pure
  Python implementation of word-sized unsigned integers that silently wrap
  around.  ("word-sized" and "machine-sized" are used equivalently and mean
  the native size, which you get using "unsigned long" in C.)
  The purpose of this class (as opposed to helper functions as above)
  is consistent typing: both Python and the annotator will propagate r_uint
  instances in the program and interpret all the operations between them as
  unsigned.  Instances of r_uint are special-cased by the code generators to
  use the appropriate low-level type and operations.
  Mixing of (signed) integers and r_uint in operations produces r_uint that
  means unsigned results.  To convert back from r_uint to signed integers, use
  intmask().


Exception rules
---------------------

Exceptions are by default not generated for simple cases.::

    #!/usr/bin/python

        lst = [1,2,3,4,5]
        item = lst[i]    # this code is not checked for out-of-bound access

        try:
            item = lst[i]
        except IndexError:
            # complain

Code with no exception handlers does not raise exceptions (after it has been
translated, that is.  When you run it on top of CPython, it may raise
exceptions, of course). By supplying an exception handler, you ask for error
checking. Without, you assure the system that the operation cannot fail.
This rule does not apply to *function calls*: any called function is
assumed to be allowed to raise any exception.

For example::

    x = 5.1
    x = x + 1.2       # not checked for float overflow
    try:
        x = x + 1.2
    except OverflowError:
        # float result too big

But::

    z = some_function(x, y)    # can raise any exception
    try:
        z = some_other_function(x, y)
    except IndexError:
        # only catches explicitly-raised IndexErrors in some_other_function()
        # other exceptions can be raised, too, and will not be caught here.

The ovfcheck() function described above follows the same rule: in case of
overflow, it explicitly raise OverflowError, which can be caught anywhere.

Exceptions explicitly raised or re-raised will always be generated.

PyPy is debuggable on top of CPython
------------------------------------

PyPy has the advantage that it is runnable on standard
CPython.  That means, we can run all of PyPy with all exception
handling enabled, so we might catch cases where we failed to
adhere to our implicit assertions.

.. _`wrapping rules`:
.. _`wrapped`:



Wrapping rules
==============

Wrapping
--------- 

PyPy is made of Python source code at two levels: there is on the one hand
*application-level code* that looks like normal Python code, and that
implements some functionalities as one would expect from Python code (e.g. one
can give a pure Python implementation of some built-in functions like
``zip()``).  There is also *interpreter-level code* for the functionalities
that must more directly manipulate interpreter data and objects (e.g. the main
loop of the interpreter, and the various object spaces).

Application-level code doesn't see object spaces explicitly: it runs using an
object space to support the objects it manipulates, but this is implicit.
There is no need for particular conventions for application-level code.  The
sequel is only about interpreter-level code.  (Ideally, no application-level
variable should be called ``space`` or ``w_xxx`` to avoid confusion.)

The ``w_`` prefixes so lavishly used in the example above indicate,
by PyPy coding convention, that we are dealing with *wrapped* (or *boxed*) objects,
that is, interpreter-level objects which the object space constructs
to implement corresponding application-level objects.  Each object
space supplies ``wrap``, ``unwrap``, ``int_w``, ``interpclass_w``,
etc. operations that move between the two levels for objects of simple
built-in types; each object space also implements other Python types
with suitable interpreter-level classes with some amount of internal
structure.

For example, an application-level Python ``list``
is implemented by the `standard object space`_ as an
instance of ``W_ListObject``, which has an instance attribute
``wrappeditems`` (an interpreter-level list which contains the
application-level list's items as wrapped objects).

The rules are described in more details below.


Naming conventions
------------------

* ``space``: the object space is only visible at
  interpreter-level code, where it is by convention passed around by the name
  ``space``.

* ``w_xxx``: any object seen by application-level code is an
  object explicitly managed by the object space.  From the
  interpreter-level point of view, this is called a *wrapped*
  object.  The ``w_`` prefix is used for any type of
  application-level object.

* ``xxx_w``: an interpreter-level container for wrapped
  objects, for example a list or a dict containing wrapped
  objects.  Not to be confused with a wrapped object that
  would be a list or a dict: these are normal wrapped objects,
  so they use the ``w_`` prefix.


Operations on ``w_xxx``
-----------------------

The core bytecode interpreter considers wrapped objects as black boxes.
It is not allowed to inspect them directly.  The allowed
operations are all implemented on the object space: they are
called ``space.xxx()``, where ``xxx`` is a standard operation
name (``add``, ``getattr``, ``call``, ``eq``...). They are documented in the
`object space document`_.

A short warning: **don't do** ``w_x == w_y`` or ``w_x is w_y``!
rationale for this rule is that there is no reason that two
wrappers are related in any way even if they contain what
looks like the same object at application-level.  To check
for equality, use ``space.is_true(space.eq(w_x, w_y))`` or
even better the short-cut ``space.eq_w(w_x, w_y)`` returning
directly a interpreter-level bool.  To check for identity,
use ``space.is_true(space.is_(w_x, w_y))`` or better
``space.is_w(w_x, w_y)``.

.. _`object space document`: objspace.html#interface

.. _`applevel-exceptions`: 

Application-level exceptions
----------------------------

Interpreter-level code can use exceptions freely.  However,
all application-level exceptions are represented as an
``OperationError`` at interpreter-level.  In other words, all
exceptions that are potentially visible at application-level
are internally an ``OperationError``.  This is the case of all
errors reported by the object space operations
(``space.add()`` etc.).

To raise an application-level exception::

    raise OperationError(space.w_XxxError, space.wrap("message"))

To catch a specific application-level exception::

    try:
        ...
    except OperationError, e:
        if not e.match(space, space.w_XxxError):
            raise
        ...

This construct catches all application-level exceptions, so we
have to match it against the particular ``w_XxxError`` we are
interested in and re-raise other exceptions.  The exception
instance ``e`` holds two attributes that you can inspect:
``e.w_type`` and ``e.w_value``.  Do not use ``e.w_type`` to
match an exception, as this will miss exceptions that are
instances of subclasses.


.. _`modules`:

Modules in PyPy
===============

Modules visible from application programs are imported from
interpreter or application level files.  PyPy reuses almost all python
modules of CPython's standard library, currently from version 2.7.3.  We
sometimes need to `modify modules`_ and - more often - regression tests
because they rely on implementation details of CPython.

If we don't just modify an original CPython module but need to rewrite
it from scratch we put it into `lib_pypy/`_ as a pure application level
module.

When we need access to interpreter-level objects we put the module into
`pypy/module`_.  Such modules use a `mixed module mechanism`_
which makes it convenient to use both interpreter- and application-level parts
for the implementation.  Note that there is no extra facility for
pure-interpreter level modules, you just write a mixed module and leave the
application-level part empty.

Determining the location of a module implementation
---------------------------------------------------

You can interactively find out where a module comes from, when running py.py.
here are examples for the possible locations::

    >>>> import sys
    >>>> sys.__file__
    '/home/hpk/pypy-dist/pypy/module/sys'

    >>>> import cPickle
    >>>> cPickle.__file__
    '/home/hpk/pypy-dist/lib_pypy/cPickle..py'

    >>>> import os
    >>>> os.__file__
    '/home/hpk/pypy-dist/lib-python/2.7/os.py'
    >>>>

Module directories / Import order
---------------------------------

Here is the order in which PyPy looks up Python modules:

*pypy/modules*

    mixed interpreter/app-level builtin modules, such as
    the ``sys`` and ``__builtin__`` module.

*contents of PYTHONPATH*

    lookup application level modules in each of the ``:`` separated
    list of directories, specified in the ``PYTHONPATH`` environment
    variable.

*lib_pypy/*

    contains pure Python reimplementation of modules.

*lib-python/2.7/*

    The modified CPython library.

.. _`modify modules`:

Modifying a CPython library module or regression test
-------------------------------------------------------

Although PyPy is very compatible with CPython we sometimes need
to change modules contained in our copy of the standard library,
often due to the fact that PyPy works with all new-style classes
by default and CPython has a number of places where it relies
on some classes being old-style.

We just maintain those changes in place,
to see what is changed we have a branch called `vendot/stdlib`
wich contains the unmodified cpython stdlib

.. _`mixed module mechanism`:
.. _`mixed modules`:

Implementing a mixed interpreter/application level Module
---------------------------------------------------------

If a module needs to access PyPy's interpreter level
then it is implemented as a mixed module.

Mixed modules are directories in `pypy/module`_ with an  `__init__.py`
file containing specifications where each name in a module comes from.
Only specified names will be exported to a Mixed Module's applevel
namespace.

Sometimes it is necessary to really write some functions in C (or
whatever target language). See `rffi`_ and `external functions
documentation`_ for details. The latter approach is cumbersome and
being phased out and former has currently quite a few rough edges.

.. _`rffi`: rffi.html
.. _`external functions documentation`: translation.html#extfunccalls

application level definitions
.............................

Application level specifications are found in the `appleveldefs`
dictionary found in ``__init__.py`` files of directories in ``pypy/module``.
For example, in `pypy/module/__builtin__/__init__.py`_ you find the following
entry specifying where ``__builtin__.locals`` comes from::

     ...
     'locals'        : 'app_inspect.locals',
     ...

The ``app_`` prefix indicates that the submodule ``app_inspect`` is
interpreted at application level and the wrapped function value for ``locals``
will be extracted accordingly.

interpreter level definitions
.............................

Interpreter level specifications are found in the ``interpleveldefs``
dictionary found in ``__init__.py`` files of directories in ``pypy/module``.
For example, in `pypy/module/__builtin__/__init__.py`_ the following
entry specifies where ``__builtin__.len`` comes from::

     ...
     'len'       : 'operation.len',
     ...

The ``operation`` submodule lives at interpreter level and ``len``
is expected to be exposable to application level.  Here is
the definition for ``operation.len()``::

    def len(space, w_obj):
        "len(object) -> integer\n\nReturn the number of items of a sequence or mapping."
        return space.len(w_obj)

Exposed interpreter level functions usually take a ``space`` argument
and some wrapped values (see `wrapping rules`_) .

You can also use a convenient shortcut in ``interpleveldefs`` dictionaries:
namely an expression in parentheses to specify an interpreter level
expression directly (instead of pulling it indirectly from a file)::

    ...
    'None'          : '(space.w_None)',
    'False'         : '(space.w_False)',
    ...

The interpreter level expression has a ``space`` binding when
it is executed.

Adding an entry under pypy/module (e.g. mymodule) entails automatic
creation of a new config option (such as --withmod-mymodule and
--withoutmod-mymodule (the later being the default)) for py.py and
translate.py.

Testing modules in ``lib_pypy/``
--------------------------------

You can go to the `lib_pypy/pypy_test/`_ directory and invoke the testing tool
("py.test" or "python ../../pypy/test_all.py") to run tests against the
lib_pypy hierarchy.  Note, that tests in `lib_pypy/pypy_test/`_ are allowed
and encouraged to let their tests run at interpreter level although
`lib_pypy/`_ modules eventually live at PyPy's application level.
This allows us to quickly test our python-coded reimplementations
against CPython.

Testing modules in ``pypy/module``
----------------------------------

Simply change to ``pypy/module`` or to a subdirectory and `run the
tests as usual`_.


Testing modules in ``lib-python``
-----------------------------------

In order to let CPython's regression tests run against PyPy
you can switch to the `lib-python/`_ directory and run
the testing tool in order to start compliance tests.
(XXX check windows compatibility for producing test reports).

Naming conventions and directory layout
===========================================

Directory and File Naming
-------------------------

- directories/modules/namespaces are always **lowercase**

- never use plural names in directory and file names

- ``__init__.py`` is usually empty except for
  ``pypy/objspace/*`` and ``pypy/module/*/__init__.py``.

- don't use more than 4 directory nesting levels

- keep filenames concise and completion-friendly.

Naming of python objects
------------------------

- class names are **CamelCase**

- functions/methods are lowercase and ``_`` separated

- objectspace classes are spelled ``XyzObjSpace``. e.g.

  - StdObjSpace
  - FlowObjSpace

- at interpreter level and in ObjSpace all boxed values
  have a leading ``w_`` to indicate "wrapped values".  This
  includes w_self.  Don't use ``w_`` in application level
  python only code.

Committing & Branching to the repository
-----------------------------------------------------

- write good log messages because several people
  are reading the diffs.

- What was previously called ``trunk`` is called the ``default`` branch in
  mercurial. Branches in mercurial are always pushed together with the rest
  of the repository. To create a ``try1`` branch (assuming that a branch named
  ``try1`` doesn't already exists) you should do::

    hg branch try1
    
  The branch will be recorded in the repository only after a commit. To switch
  back to the default branch::
  
    hg update default
    
  For further details use the help or refer to the `official wiki`_::
  
    hg help branch

.. _`official wiki`: http://mercurial.selenic.com/wiki/Branch

.. _`using development tracker`:

Using the development bug/feature tracker
=========================================

We have a `development tracker`_, based on Richard Jones'
`roundup`_ application.  You can file bugs,
feature requests or see what's going on
for the next milestone, both from an E-Mail and from a
web interface.

.. _`development tracker`: https://codespeak.net/issue/pypy-dev/

use your codespeak login or register
------------------------------------

If you have an existing codespeak account, you can use it to login within the
tracker. Else, you can `register with the tracker`_ easily.


.. _`register with the tracker`: https://codespeak.net/issue/pypy-dev/user?@template=register
.. _`roundup`: http://roundup.sourceforge.net/


.. _`testing in PyPy`:
.. _`test-design`: 

Testing in PyPy
===============

Our tests are based on the `py.test`_ tool which lets you write
unittests without boilerplate.  All tests of modules
in a directory usually reside in a subdirectory **test**.  There are
basically two types of unit tests:

- **Interpreter Level tests**. They run at the same level as PyPy's
  interpreter.

- **Application Level tests**. They run at application level which means
  that they look like straight python code but they are interpreted by PyPy.

.. _`standard object space`: objspace.html#standard-object-space
.. _`objectspace`: objspace.html
.. _`py.test`: http://pytest.org/

Interpreter level tests
-----------------------

You can write test functions and methods like this::

    def test_something(space):
        # use space ...

    class TestSomething(object):
        def test_some(self):
            # use 'self.space' here

Note that the prefix `test` for test functions and `Test` for test
classes is mandatory.  In both cases you can import Python modules at
module global level and use plain 'assert' statements thanks to the
usage of the `py.test`_ tool.

Application Level tests
-----------------------

For testing the conformance and well-behavedness of PyPy it
is often sufficient to write "normal" application-level
Python code that doesn't need to be aware of any particular
coding style or restrictions.  If we have a choice we often
use application level tests which usually look like this::

    def app_test_something():
        # application level test code

    class AppTestSomething(object):
        def test_this(self):
            # application level test code

These application level test functions will run on top
of PyPy, i.e. they have no access to interpreter details.
You cannot use imported modules from global level because
they are imported at interpreter-level while you test code
runs at application level. If you need to use modules
you have to import them within the test function.

Another possibility to pass in data into the AppTest is to use
the ``setup_class`` method of the AppTest. All wrapped objects that are
attached to the class there and start with ``w_`` can be accessed
via self (but without the ``w_``) in the actual test method. An example::

    class AppTestErrno(object):
        def setup_class(cls):
            cls.w_d = cls.space.wrap({"a": 1, "b", 2})

        def test_dict(self):
            assert self.d["a"] == 1
            assert self.d["b"] == 2

.. _`run the tests as usual`:

Command line tool test_all
--------------------------

You can run almost all of PyPy's tests by invoking::

  python test_all.py file_or_directory

which is a synonym for the general `py.test`_ utility
located in the ``py/bin/`` directory.  For switches to
modify test execution pass the ``-h`` option.

Coverage reports
----------------

In order to get coverage reports the `pytest-cov`_ plugin is included.
it adds some extra requirements ( coverage_ and `cov-core`_ )
and can once they are installed coverage testing can be invoked via::

  python test_all.py --cov file_or_direcory_to_cover file_or_directory

.. _`pytest-cov`: http://pypi.python.org/pypi/pytest-cov
.. _`coverage`: http://pypi.python.org/pypi/coverage
.. _`cov-core`: http://pypi.python.org/pypi/cov-core

Test conventions
----------------

- adding features requires adding appropriate tests.  (It often even
  makes sense to first write the tests so that you are sure that they
  actually can fail.)

- All over the pypy source code there are test/ directories
  which contain unit tests.  Such scripts can usually be executed
  directly or are collectively run by pypy/test_all.py

.. _`change documentation and website`:

Changing documentation and website
==================================

documentation/website files in your local checkout
---------------------------------------------------

Most of the PyPy's documentation is kept in `pypy/doc`.
You can simply edit or add '.rst' files which contain ReST-markuped
files.  Here is a `ReST quickstart`_ but you can also just look
at the existing documentation and see how things work.

.. _`ReST quickstart`: http://docutils.sourceforge.net/docs/user/rst/quickref.html

Note that the web site of http://pypy.org/ is maintained separately.
For now it is in the repository https://bitbucket.org/pypy/pypy.org

Automatically test documentation/website changes
------------------------------------------------

.. _`sphinx home page`:
.. _`sphinx`: http://sphinx.pocoo.org/

We automatically check referential integrity and ReST-conformance.  In order to
run the tests you need sphinx_ installed.  Then go to the local checkout
of the documentation directory and run the Makefile::

    cd pypy/doc
    make html

If you see no failures chances are high that your modifications at least
don't produce ReST-errors or wrong local references. Now you will have `.html`
files in the documentation directory which you can point your browser to!

Additionally, if you also want to check for remote references inside
the documentation issue::

    make linkcheck

which will check that remote URLs are reachable.


.. include:: _ref.txt
