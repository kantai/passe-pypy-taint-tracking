===============
The CLI backend
===============

The goal of GenCLI is to compile RPython programs to the CLI virtual
machine.


Target environment and language
===============================

The target of GenCLI is the Common Language Infrastructure environment
as defined by the `Standard Ecma 335`_.

While in an ideal world we might suppose GenCLI to run fine with
every implementation conforming to that standard, we know the world we
live in is far from ideal, so extra efforts can be needed to maintain
compatibility with more than one implementation.

At the moment of writing the two most popular implementations of the
standard are supported: Microsoft Common Language Runtime (CLR) and
Mono.

Then we have to choose how to generate the real executables. There are
two main alternatives: generating source files in some high level
language (such as C#) or generating assembly level code in
Intermediate Language (IL).

The IL approach is much faster during the code generation
phase, because it doesn't need to call a compiler. By contrast the
high level approach has two main advantages:

  - the code generation part could be easier because the target
    language supports high level control structures such as
    structured loops;
  
  - the generated executables take advantage of compiler's
    optimizations.

In reality the first point is not an advantage in the PyPy context,
because the `flow graph`_ we start from is quite low level and Python
loops are already expressed in terms of branches (i.e., gotos).

About the compiler optimizations we must remember that the flow graph
we receive from earlier stages is already optimized: PyPy implements
a number of optimizations such a constant propagation and
dead code removal, so it's not obvious if the compiler could
do more.

Moreover by emitting IL instruction we are not constrained to rely on
compiler choices but can directly choose how to map CLI opcodes: since
the backend often know more than the compiler about the context, we
might expect to produce more efficient code by selecting the most
appropriate instruction; e.g., we can check for arithmetic overflow
only when strictly necessary.

The last but not least reason for choosing the low level approach is
flexibility in how to get an executable starting from the IL code we
generate:

  - write IL code to a file, then call the ilasm assembler;
  
  - directly generate code on the fly by accessing the facilities
    exposed by the System.Reflection.Emit API.


Handling platform differences
=============================

Since our goal is to support both Microsoft CLR we have to handle the
differences between the twos; in particular the main differences are
in the name of the helper tools we need to call:

=============== ======== ======
Tool            CLR      Mono
=============== ======== ======
IL assembler    ilasm    ilasm2
C# compiler     csc      gmcs
Runtime         ...      mono
=============== ======== ======

The code that handles these differences is located in the sdk.py
module: it defines an abstract class which exposes some methods
returning the name of the helpers and one subclass for each of the two
supported platforms.

Since Microsoft ``ilasm`` is not capable of compiling the PyPy
standard interpreter due to its size, on Windows machines we also look
for an existing Mono installation: if present, we use CLR for
everything except the assembling phase, for which we use Mono's
``ilasm2``.


Targeting the CLI Virtual Machine
=================================

In order to write a CLI backend we have to take a number of decisions.
First, we have to choose the typesystem to use: given that CLI
natively supports primitives like classes and instances,
ootypesystem is the most natural choice.

Once the typesystem has been chosen there is a number of steps we have
to do for completing the backend:

  - map ootypesystem's types to CLI Common Type System's
    types;
  
  - map ootypesystem's low level operation to CLI instructions;
  
  - map Python exceptions to CLI exceptions;
  
  - write a code generator that translates a flow graph
    into a list of CLI instructions;
  
  - write a class generator that translates ootypesystem
    classes into CLI classes.


Mapping primitive types
-----------------------

The `rtyper`_ give us a flow graph annotated with types belonging to
ootypesystem: in order to produce CLI code we need to translate these
types into their Common Type System equivalents.

For numeric types the conversion is straightforward, since
there is a one-to-one mapping between the two typesystems, so that
e.g. Float maps to float64.

For character types the choice is more difficult: RPython has two
distinct types for plain ASCII and Unicode characters (named UniChar),
while .NET only supports Unicode with the char type. There are at
least two ways to map plain Char to CTS:

  - map UniChar to char, thus maintaining the original distinction
    between the two types: this has the advantage of being a
    one-to-one translation, but has the disadvantage that RPython
    strings will not be recognized as .NET strings, since they only
    would be sequences of bytes;
  
  - map both char, so that Python strings will be treated as strings
    also by .NET: in this case there could be problems with existing
    Python modules that use strings as sequences of byte, such as the
    built-in struct module, so we need to pay special attention.

We think that mapping Python strings to .NET strings is
fundamental, so we chose the second option.

Mapping built-in types
----------------------

As we saw in section ootypesystem defines a set of types that take
advantage of built-in types offered by the platform.

For the sake of simplicity we decided to write wrappers
around .NET classes in order to match the signatures required by
pypylib.dll:

=================== ===========================================
ootype              CLI
=================== ===========================================
String              System.String
StringBuilder       System.Text.StringBuilder
List                System.Collections.Generic.List<T>
Dict                System.Collections.Generic.Dictionary<K, V>
CustomDict          pypy.runtime.Dict
DictItemsIterator   pypy.runtime.DictItemsIterator
=================== ===========================================

Wrappers exploit inheritance for wrapping the original classes, so,
for example, pypy.runtime.List<T> is a subclass of
System.Collections.Generic.List<T> that provides methods whose names
match those found in the _GENERIC_METHODS of ootype.List

The only exception to this rule is the String class, which is not
wrapped since in .NET we can not subclass System.String.  Instead, we
provide a bunch of static methods in pypylib.dll that implement the
methods declared by ootype.String._GENERIC_METHODS, then we call them
by explicitly passing the string object in the argument list.


Mapping instructions
--------------------

PyPy's low level operations are expressed in Static Single Information
(SSI) form, such as this::

    v2 = int_add(v0, v1)

By contrast the CLI virtual machine is stack based, which means the
each operation pops its arguments from the top of the stacks and
pushes its result there. The most straightforward way to translate SSI
operations into stack based operations is to explicitly load the
arguments and store the result into the appropriate places::

    LOAD v0
    LOAD v1
    int_add
    STORE v2

The code produced works correctly but has some inefficiency issues that
can be addressed during the optimization phase.

The CLI Virtual Machine is fairly expressive, so the conversion
between PyPy's low level operations and CLI instruction is relatively
simple: many operations maps directly to the corresponding
instruction, e.g int_add and sub.

By contrast some instructions do not have a direct correspondent and
have to be rendered as a sequence of CLI instructions: this is the
case of the "less-equal" and "greater-equal" family of instructions,
that are rendered as "greater" or "less" followed by a boolean "not",
respectively.

Finally, there are some instructions that cannot be rendered directly
without increasing the complexity of the code generator, such as
int_abs (which returns the absolute value of its argument).  These
operations are translated by calling some helper function written in
C#.

The code that implements the mapping is in the modules opcodes.py.

Mapping exceptions
------------------

Both RPython and CLI have their own set of exception classes: some of
these are pretty similar; e.g., we have OverflowError,
ZeroDivisionError and IndexError on the first side and
OverflowException, DivideByZeroException and IndexOutOfRangeException
on the other side.

The first attempt was to map RPython classes to their corresponding
CLI ones: this worked for simple cases, but it would have triggered
subtle bugs in more complex ones, because the two exception
hierarchies don't completely overlap.

At the moment we've chosen to build an RPython exception hierarchy
completely independent from the CLI one, but this means that we can't
rely on exceptions raised by built-in operations.  The currently
implemented solution is to do an exception translation on-the-fly.

As an example consider the RPython int_add_ovf operation, that sums
two integers and raises an OverflowError exception in case of
overflow. For implementing it we can use the built-in add.ovf CLI
instruction that raises System.OverflowException when the result
overflows, catch that exception and throw a new one::

    .try 
    { 
        ldarg 'x_0'
        ldarg 'y_0'
        add.ovf 
        stloc 'v1'
        leave __check_block_2 
    } 
    catch [mscorlib]System.OverflowException 
    { 
        newobj instance void class OverflowError::.ctor() 
        throw 
    } 


Translating flow graphs
-----------------------

As we saw previously in PyPy function and method bodies are
represented by flow graphs that we need to translate CLI IL code. Flow
graphs are expressed in a format that is very suitable for being
translated to low level code, so that phase is quite straightforward,
though the code is a bit involved because we need to take care of three
different types of blocks.

The code doing this work is located in the Function.render
method in the file function.py.

First of all it searches for variable names and types used by
each block; once they are collected it emits a .local IL
statement used for indicating the virtual machine the number and type
of local variables used.

Then it sequentially renders all blocks in the graph, starting from the
start block; special care is taken for the return block which is
always rendered at last to meet CLI requirements.

Each block starts with an unique label that is used for jumping
across, followed by the low level instructions the block is composed
of; finally there is some code that jumps to the appropriate next
block.

Conditional and unconditional jumps are rendered with their
corresponding IL instructions: brtrue, brfalse.

Blocks that needs to catch exceptions use the native facilities
offered by the CLI virtual machine: the entire block is surrounded by
a .try statement followed by as many catch as needed: each catching
sub-block then branches to the appropriate block::


  # RPython
  try:
      # block0
      ...
  except ValueError:
      # block1
      ...
  except TypeError:
      # block2
      ...

  // IL
  block0: 
    .try {
        ...
        leave block3
     }
     catch ValueError {
        ...
        leave block1
      }
      catch TypeError {
        ...
        leave block2
      }
  block1:
      ...
      br block3
  block2:
      ...
      br block3
  block3:
      ...

There is also an experimental feature that makes GenCLI to use its own
exception handling mechanism instead of relying on the .NET
one. Surprisingly enough, benchmarks are about 40% faster with our own
exception handling machinery.


Translating classes
-------------------

As we saw previously, the semantic of ootypesystem classes
is very similar to the .NET one, so the translation is mostly
straightforward.

The related code is located in the module class\_.py.  Rendered classes
are composed of four parts:

  - fields;
  - user defined methods;
  - default constructor;
  - the ToString method, mainly for testing purposes

Since ootype implicitly assumes all method calls to be late bound, as
an optimization before rendering the classes we search for methods
that are not overridden in subclasses, and declare as "virtual" only
the one that needs to.

The constructor does nothing more than calling the base class
constructor and initializing class fields to their default value.

Inheritance is straightforward too, as it is natively supported by
CLI. The only noticeable thing is that we map ootypesystem's ROOT
class to the CLI equivalent System.Object.

The Runtime Environment
-----------------------

The runtime environment is a collection of helper classes and
functions used and referenced by many of the GenCLI submodules. It is
written in C#, compiled to a DLL (Dynamic Link Library), then linked
to generated code at compile-time.

The DLL is called pypylib and is composed of three parts:

  - a set of helper functions used to implements complex RPython
    low-level instructions such as runtimenew and ooparse_int;

  - a set of helper classes wrapping built-in types

  - a set of helpers used by the test framework


The first two parts are contained in the pypy.runtime namespace, while
the third is in the pypy.test one.


Testing GenCLI
==============

As the rest of PyPy, GenCLI is a test-driven project: there is at
least one unit test for almost each single feature of the
backend. This development methodology allowed us to early discover
many subtle bugs and to do some big refactoring of the code with the
confidence not to break anything.

The core of the testing framework is in the module
rpython.translator.cli.test.runtest; one of the most important function
of this module is compile_function(): it takes a Python function,
compiles it to CLI and returns a Python object that runs the just
created executable when called.

This way we can test GenCLI generated code just as if it were a simple
Python function; we can also directly run the generated executable,
whose default name is main.exe, from a shell: the function parameters
are passed as command line arguments, and the return value is printed
on the standard output::

    # Python source: foo.py
    from rpython.translator.cli.test.runtest import compile_function

    def foo(x, y):
        return x+y, x*y

    f = compile_function(foo, [int, int])
    assert f(3, 4) == (7, 12)


    # shell
    $ mono main.exe 3 4
    (7, 12)

GenCLI supports only few RPython types as parameters: int, r_uint,
r_longlong, r_ulonglong, bool, float and one-length strings (i.e.,
chars). By contrast, most types are fine for being returned: these
include all primitive types, list, tuples and instances.

Installing Python for .NET on Linux
===================================

With the CLI backend, you can access .NET libraries from RPython;
programs using .NET libraries will always run when translated, but you
might also want to test them on top of CPython.

To do so, you can install `Python for .NET`_. Unfortunately, it does
not work out of the box under Linux.

To make it work, download and unpack the source package of Python
for .NET; the only version tested with PyPy is the 1.0-rc2, but it
might work also with others. Then, you need to create a file named
Python.Runtime.dll.config at the root of the unpacked archive; put the
following lines inside the file (assuming you are using Python 2.7)::

  <configuration>
    <dllmap dll="python27" target="libpython2.7.so.1.0" os="!windows"/>
  </configuration>

The installation should be complete now. To run Python for .NET,
simply type ``mono python.exe``.


.. _`Standard Ecma 335`: http://www.ecma-international.org/publications/standards/Ecma-335.htm
.. _`flow graph`: translation.html#the-flow-model
.. _`rtyper`: rtyper.html
.. _`Python for .NET`: http://pythonnet.sourceforge.net/
