Some discussion about external objects in ootype
================================================

Current approach:

* SomeCliXxx for .NET backend

SomeCliXxx
----------

* Supports method overloading

* Supports inheritance in a better way

* Supports static methods

Would be extremely cool to generalize the approach to be useful also for the
JVM backend.  Here are some notes:

* There should be one mechanism, factored out nicely out of any backend,
  to support any possible backend (cli, jvm for now).

* This approach might be eventually extended by a backend itself, but
  as much as possible code should be factored out.

* Backend should take care itself about creating such classes, either
  manually or automatically.

* Should support superset of needs of all backends (ie callbacks,
  method overloading, etc.)


Proposal of alternative approach
================================

The goal of the task is to let RPython program access "external
entities" which are available in the target platform; these include:

  - external classes (e.g. for .NET: System.Collections.ArrayList)

  - external prebuilt instances (e.g. for .NET: typeof(System.Console))

External entities should behave as much as possible as "internal
entities".

Moreover, we want to preserve the possibility of *testing* RPython
programs on top of CPython if possible. For example, it should be
possible to RPython programs using .NET external objects using
PythonNet; for JVM, there are JPype_ and JTool_, to be investigated:

.. _JPype: http://jpype.sourceforge.net/
.. _JTool: http://wiki.europython.eu/Talks/Jtool%20Java%20In%20The%20Python%20Vm

How to represent types
----------------------

First, some definitions: 

  - high-level types are the types used by the annotator
    (SomeInteger() & co.)

  - low-level types are the types used by the rtyper (Signed & co.)

  - platform-level types are the types used by the backends (e.g. int32 for
    .NET)

Usually, RPython types are described "top-down": we start from the
annotation, then the rtyper transforms the high-level types into
low-level types, then the backend transforms low-level types into
platform-level types. E.g. for .NET, SomeInteger() -> Signed -> int32.

External objects are different: we *already* know the platform-level
types of our objects and we can't modify them. What we need to do is
to specify an annotation that after the high-level -> low-level ->
platform-level transformation will give us the correct types.

For primitive types it is usually easy to find the correct annotation;
if we have an int32, we know that it's ootype is Signed and the
corresponding annotation is SomeInteger().

For non-primitive types such as classes, we must use a "bottom-up"
approach: first, we need a description of platform-level interface of
the class; then we construct the corresponding low-level type and
teach the backends how to treat such "external types". Finally, we
wrap the low-level types into special "external annotation".

For example, consider a simple existing .NET class::

    class Foo {
        public float bar(int x, int y) { ... }
    }

The corresponding low-level type could be something like this::

    Foo = ootype.ExternalInstance({'bar': ([Signed, Signed], Float)})

Then, the annotation for Foo's instances is SomeExternalInstance(Foo).
This way, the transformation from high-level types to platform-level
types is straightforward and correct.

Finally, we need support for static methods: similarly for classes, we
can define an ExternalStaticMeth low-level type and a
SomeExternalStaticMeth annotation.


How to describe types
---------------------

To handle external objects we must specify their signatures. For CLI
and JVM the job can be easily automatized, since the objects have got
precise signatures.


RPython interface
-----------------

External objects are exposed as special Python objects that gets
annotated as SomeExternalXXX. Each backend can choose its own way to
provide these objects to the RPython programmer.

External classes will be annotated as SomeExternalClass; two
operations are allowed:

  - call: used to instantiate the class, return an object which will
    be annotated as SomeExternalInstance.

  - access to static methods: return an object which will be annotated
    as SomeExternalStaticMeth.

Instances are annotated as SomeExternalInstance. Prebuilt external objects are
annotated as SomeExternalInstance(const=...).

Open issues
-----------

Exceptions
~~~~~~~~~~

.NET and JVM users want to catch external exceptions in a natural way;
e.g.::

    try:
        ...
    except System.OverflowException:
        ...

This is not straightforward because to make the flow objspace happy the
object which represent System.OverflowException must be a real Python
class that inherits from Exception.

This means that the Python objects which represent external classes
must be Python classes itself, and that classes representing
exceptions must be special cased and made subclasses of Exception.


Inheritance
~~~~~~~~~~~

It would be nice to allow programmers to inherit from an external
class. Not sure about the implications, though.

Special methods/properties
~~~~~~~~~~~~~~~~~~~~~~~~~~

In .NET there are special methods that can be accessed using a special
syntax, for example indexer or properties. It would be nice to have in
RPython the same syntax as C#, although we can live without that.


Implementation details
----------------------

The CLI backend use a similar approach right now, but it could be
necessary to rewrite a part of it.

To represent low-level types, it uses NativeInstance, a subclass of
ootype.Instance that contains all the information needed by the
backend to reference the class (e.g., the namespace). It also supports
overloading.

For annotations, it reuses SomeOOInstance, which is also a wrapper
around a low-level type but it has been designed for low-level
helpers. It might be saner to use another annotation not to mix apples
and oranges, maybe factoring out common code.

I don't know whether and how much code can be reused from the existing
bltregistry.
