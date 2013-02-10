===============================
The ``clr`` module for PyPy.NET
===============================

PyPy.NET give you access to the surrounding .NET environment via the
``clr`` module. This module is still experimental: some features are
still missing and its interface might change in next versions, but
it's still useful to experiment a bit with PyPy.NET.

PyPy.NET provides an import hook that lets you to import .NET namespaces
seamlessly as they were normal Python modules.  Then, 

PyPY.NET native classes try to behave as much as possible in the
"expected" way both for the developers used to .NET and for the ones
used to Python.

In particular, the following features are mapped one to one because
they exist in both worlds:

  - .NET constructors are mapped to the Python __init__ method;

  - .NET instance methods are mapped to Python methods;

  - .NET static methods are mapped to Python static methods (belonging
    to the class);

  - .NET properties are mapped to property-like Python objects (very
    similar to the Python ``property`` built-in);

  - .NET indexers are mapped to Python __getitem__ and __setitem__;

  - .NET enumerators are mapped to Python iterators.

Moreover, all the usual Python features such as bound and unbound
methods are available as well.

Example of usage
================

Here is an example of interactive session using the ``clr`` module::

    >>>> from System.Collections import ArrayList
    >>>> obj = ArrayList()
    >>>> obj.Add(1)
    0
    >>>> obj.Add(2)
    1
    >>>> obj.Add("foo")
    2
    >>>> print obj[0], obj[1], obj[2]
    1 2 foo
    >>>> print obj.Count
    3

Conversion of parameters
========================

When calling a .NET method Python objects are converted to .NET
objects.  Lots of effort have been taken to make the conversion as
much transparent as possible; in particular, all the primitive types
such as int, float and string are converted to the corresponding .NET
types (e.g., ``System.Int32``, ``System.Float64`` and
``System.String``).

Python objects without a corresponding .NET types (e.g., instances of
user classes) are passed as "black boxes", for example to be stored in
some sort of collection.

The opposite .NET to Python conversions happens for the values returned
by the methods. Again, primitive types are converted in a
straightforward way; non-primitive types are wrapped in a Python object, 
so that they can be treated as usual.

Overload resolution
===================

When calling an overloaded method, PyPy.NET tries to find the best
overload for the given arguments; for example, consider the
``System.Math.Abs`` method::


    >>>> from System import Math
    >>>> Math.Abs(-42)
    42
    >>>> Math.Abs(-42.0)
    42.0

``System.Math.Abs`` has got overloadings both for integers and floats:
in the first case we call the method ``System.Math.Abs(int32)``, while
in the second one we call the method ``System.Math.Abs(float64)``.

If the system can't find a best overload for the given parameters, a
TypeError exception is raised.


Generic classes
================

Generic classes are fully supported.  To instantiate a generic class, you need
to use the ``[]`` notation::

    >>>> from System.Collections.Generic import List
    >>>> mylist = List[int]()
    >>>> mylist.Add(42)
    >>>> mylist.Add(43)
    >>>> mylist.Add("foo")
    Traceback (most recent call last):
      File "<console>", line 1, in <interactive>
    TypeError: No overloads for Add could match
    >>>> mylist[0]
    42
    >>>> for item in mylist: print item
    42
    43


External assemblies and Windows Forms
=====================================

By default, you can only import .NET namespaces that belongs to already loaded
assemblies.  To load additional .NET assemblies, you can use
``clr.AddReferenceByPartialName``.  The following example loads
``System.Windows.Forms`` and ``System.Drawing`` to display a simple Windows
Form displaying the usual "Hello World" message::

    >>>> import clr
    >>>> clr.AddReferenceByPartialName("System.Windows.Forms")
    >>>> clr.AddReferenceByPartialName("System.Drawing")
    >>>> from System.Windows.Forms import Application, Form, Label
    >>>> from System.Drawing import Point
    >>>>
    >>>> frm = Form()
    >>>> frm.Text = "The first pypy-cli Windows Forms app ever"
    >>>> lbl = Label()
    >>>> lbl.Text = "Hello World!"
    >>>> lbl.AutoSize = True
    >>>> lbl.Location = Point(100, 100)
    >>>> frm.Controls.Add(lbl)
    >>>> Application.Run(frm)

Unfortunately at the moment you can't do much more than this with Windows
Forms, because we still miss support for delegates and so it's not possible
to handle events.
