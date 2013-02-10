
Welcome to PyPy Development
=============================================

The PyPy project aims at producing a flexible and fast Python_
implementation.  The guiding idea is to translate a Python-level
description of the Python language itself to lower level languages.
Rumors have it that the secret goal is being faster-than-C which is
nonsense, isn't it?  `more...`_

Getting into PyPy ... 
=============================================

* `Getting started`_: how to install and run the PyPy Python interpreter

* `FAQ`_: some frequently asked questions.

* `Release 2.0 beta 1`_: the latest official release

* `PyPy Blog`_: news and status info about PyPy 

* `Papers`_: Academic papers, talks, and related projects

* `speed.pypy.org`_: Daily benchmarks of how fast PyPy is

* `potential project ideas`_: In case you want to get your feet wet...

Documentation for the PyPy Python Interpreter
===============================================

New features of PyPy's Python Interpreter and 
Translation Framework: 

  * `Differences between PyPy and CPython`_
  * `What PyPy can do for your objects`_
  * `Continulets and greenlets`_
  * `JIT Generation in PyPy`_ 
  * `Sandboxing Python code`_

Status_ of the project.


Mailing lists, bug tracker, IRC channel
=============================================

* `Development mailing list`_: development and conceptual
  discussions. 

* `Mercurial commit mailing list`_: updates to code and
  documentation. 

* `Development bug/feature tracker`_: filing bugs and feature requests. 

* **IRC channel #pypy on freenode**: Many of the core developers are hanging out 
  at #pypy on irc.freenode.net.  You are welcome to join and ask questions
  (if they are not already developed in the FAQ_).
  You can find logs of the channel here_.

Meeting PyPy developers
=======================

The PyPy developers are organizing sprints and presenting results at
conferences all year round. They will be happy to meet in person with
anyone interested in the project.  Watch out for sprint announcements
on the `development mailing list`_.

.. _Python: http://docs.python.org/index.html
.. _`more...`: architecture.html#mission-statement 
.. _`PyPy blog`: http://morepypy.blogspot.com/
.. _`development bug/feature tracker`: https://bugs.pypy.org
.. _here: http://tismerysoft.de/pypy/irc-logs/pypy
.. _`Mercurial commit mailing list`: http://python.org/mailman/listinfo/pypy-commit
.. _`development mailing list`: http://python.org/mailman/listinfo/pypy-dev
.. _`FAQ`: faq.html
.. _`Getting Started`: getting-started.html
.. _`Papers`: extradoc.html
.. _`Videos`: video-index.html
.. _`Release 2.0 beta 1`: http://pypy.org/download.html
.. _`speed.pypy.org`: http://speed.pypy.org
.. _`RPython toolchain`: translation.html
.. _`potential project ideas`: project-ideas.html

Project Documentation
=====================================

PyPy was funded by the EU for several years. See the `web site of the EU
project`_ for more details.

.. _`web site of the EU project`: http://pypy.org

architecture_ gives a complete view of PyPy's basic design. 

`coding guide`_ helps you to write code for PyPy (especially also describes
coding in RPython a bit). 

`sprint reports`_ lists reports written at most of our sprints, from
2003 to the present.

`papers, talks and related projects`_ lists presentations 
and related projects as well as our published papers.

`PyPy video documentation`_ is a page linking to the videos (e.g. of talks and
introductions) that are available.

`Technical reports`_ is a page that contains links to the
reports that we submitted to the European Union.

`development methodology`_ describes our sprint-driven approach.

`LICENSE`_ contains licensing details (basically a straight MIT-license). 

`Glossary`_ of PyPy words to help you align your inner self with
the PyPy universe.


Status
===================================

PyPy can be used to run Python programs on Linux, OS/X,
Windows, on top of .NET, and on top of Java.
To dig into PyPy it is recommended to try out the current
Mercurial default branch, which is always working or mostly working,
instead of the latest release, which is `2.0 beta1`__.

.. __: release-2.0.0-beta1.html

PyPy is mainly developed on Linux and Mac OS X.  Windows is supported,
but platform-specific bugs tend to take longer before we notice and fix
them.  Linux 64-bit machines are supported (though it may also take some
time before we notice and fix bugs).

PyPy's own tests `summary`_, daily updated, run through BuildBot infrastructure.
You can also find CPython's compliance tests run with compiled ``pypy-c``
executables there.


Source Code Documentation
===============================================

`object spaces`_ discusses the object space interface 
and several implementations. 

`bytecode interpreter`_ explains the basic mechanisms 
of the bytecode interpreter and virtual machine. 

`interpreter optimizations`_ describes our various strategies for
improving the performance of our interpreter, including alternative
object implementations (for strings, dictionaries and lists) in the
standard object space.

`translation`_ is a detailed overview of our translation process.  The
rtyper_ is the largest component of our translation process.

`dynamic-language translation`_ is a paper that describes
the translation process, especially the flow object space
and the annotator in detail. (This document is one
of the `EU reports`_.)

`low-level encapsulation`_ describes how our approach hides
away a lot of low level details. This document is also part
of the `EU reports`_.

`translation aspects`_ describes how we weave different
properties into our interpreter during the translation
process. This document is also part of the `EU reports`_.

`garbage collector`_ strategies that can be used by the virtual
machines produced by the translation process.

`parser`_ contains (outdated, unfinished) documentation about
the parser.

`rlib`_ describes some modules that can be used when implementing programs in
RPython.

`configuration documentation`_ describes the various configuration options that
allow you to customize PyPy.

`CLI backend`_ describes the details of the .NET backend.

`JIT Generation in PyPy`_ describes how we produce the Python Just-in-time Compiler
from our Python interpreter.



.. _`FAQ`: faq.html
.. _Glossary: glossary.html
.. _`PyPy video documentation`: video-index.html
.. _parser: parser.html
.. _`development methodology`: dev_method.html
.. _`sprint reports`: sprint-reports.html
.. _`papers, talks and related projects`: extradoc.html
.. _`object spaces`: objspace.html 
.. _`interpreter optimizations`: interpreter-optimizations.html 
.. _`translation`: translation.html 
.. _`dynamic-language translation`: https://bitbucket.org/pypy/extradoc/raw/tip/eu-report/D05.1_Publish_on_translating_a_very-high-level_description.pdf
.. _`low-level encapsulation`: low-level-encapsulation.html
.. _`translation aspects`: translation-aspects.html
.. _`configuration documentation`: config/
.. _`coding guide`: coding-guide.html 
.. _`architecture`: architecture.html 
.. _`getting started`: getting-started.html 
.. _`bytecode interpreter`: interpreter.html 
.. _`EU reports`: index-report.html
.. _`Technical reports`: index-report.html
.. _`summary`: http://buildbot.pypy.org/summary
.. _`ideas for PyPy related projects`: project-ideas.html
.. _`Nightly builds and benchmarks`: http://tuatara.cs.uni-duesseldorf.de/benchmark.html
.. _`directory reference`: 
.. _`rlib`: rlib.html
.. _`Sandboxing Python code`: sandbox.html
.. _`LICENSE`: https://bitbucket.org/pypy/pypy/src/default/LICENSE

PyPy directory cross-reference 
------------------------------

Here is a fully referenced alphabetical two-level deep 
directory overview of PyPy: 

================================   =========================================== 
Directory                          explanation/links
================================   =========================================== 
`pypy/annotation/`_                `type inferencing code`_ for `RPython`_ programs 

`pypy/bin/`_                       command-line scripts, mainly `py.py`_ and `translatorshell.py`_

`pypy/config/`_                    handles the numerous options for building and running PyPy

`pypy/doc/`_                       text versions of PyPy developer documentation

`pypy/doc/config/`_                documentation for the numerous translation options

`pypy/doc/discussion/`_            drafts of ideas and documentation

``doc/*/``                         other specific documentation topics or tools

`pypy/interpreter/`_               `bytecode interpreter`_ and related objects
                                   (frames, functions, modules,...) 

`pypy/interpreter/pyparser/`_      interpreter-level Python source parser

`pypy/interpreter/astcompiler/`_   interpreter-level bytecode compiler, via an AST
                                   representation

`pypy/module/`_                    contains `mixed modules`_ implementing core modules with 
                                   both application and interpreter level code.
                                   Not all are finished and working.  Use the ``--withmod-xxx``
                                   or ``--allworkingmodules`` translation options.

`pypy/objspace/`_                  `object space`_ implementations

`pypy/objspace/flow/`_             the FlowObjSpace_ implementing `abstract interpretation`_

`pypy/objspace/std/`_              the StdObjSpace_ implementing CPython's objects and types

`pypy/rlib/`_                      a `"standard library"`_ for RPython_ programs

`pypy/rpython/`_                   the `RPython Typer`_ 

`pypy/rpython/lltypesystem/`_      the `low-level type system`_ for C-like backends

`pypy/rpython/ootypesystem/`_      the `object-oriented type system`_ for OO backends

`pypy/rpython/memory/`_            the `garbage collector`_ construction framework

`pypy/tool/`_                      various utilities and hacks used from various places 

`pypy/tool/algo/`_                 general-purpose algorithmic and mathematic
                                   tools

`pypy/tool/pytest/`_               support code for our `testing methods`_

`pypy/translator/`_                translation_ backends and support code

`pypy/translator/backendopt/`_     general optimizations that run before a backend generates code

`pypy/translator/c/`_              the `GenC backend`_, producing C code from an
                                   RPython program (generally via the rtyper_)

`pypy/translator/cli/`_            the `CLI backend`_ for `.NET`_ (Microsoft CLR or Mono_)

`pypy/translator/goal/`_           our `main PyPy-translation scripts`_ live here

`pypy/translator/jvm/`_            the Java backend

`pypy/translator/tool/`_           helper tools for translation, including the Pygame
                                   `graph viewer`_

``*/test/``                        many directories have a test subdirectory containing test 
                                   modules (see `Testing in PyPy`_) 

``_cache/``                        holds cache files from internally `translating application 
                                   level to interpreterlevel`_ code.   
================================   =========================================== 

.. _`bytecode interpreter`: interpreter.html
.. _`translating application level to interpreterlevel`: geninterp.html
.. _`Testing in PyPy`: coding-guide.html#testing-in-pypy 
.. _`mixed modules`: coding-guide.html#mixed-modules 
.. _`modules`: coding-guide.html#modules 
.. _`basil`: http://people.cs.uchicago.edu/~jriehl/BasilTalk.pdf
.. _`object space`: objspace.html
.. _FlowObjSpace: objspace.html#the-flow-object-space 
.. _`transparent proxies`: objspace-proxies.html#tproxy
.. _`Differences between PyPy and CPython`: cpython_differences.html
.. _`What PyPy can do for your objects`: objspace-proxies.html
.. _`Continulets and greenlets`: stackless.html
.. _StdObjSpace: objspace.html#the-standard-object-space 
.. _`abstract interpretation`: http://en.wikipedia.org/wiki/Abstract_interpretation
.. _`rpython`: coding-guide.html#rpython 
.. _`type inferencing code`: translation.html#the-annotation-pass 
.. _`RPython Typer`: translation.html#rpython-typer 
.. _`testing methods`: coding-guide.html#testing-in-pypy
.. _`translation`: translation.html 
.. _`GenC backend`: translation.html#genc 
.. _`CLI backend`: cli-backend.html
.. _`py.py`: getting-started-python.html#the-py.py-interpreter
.. _`translatorshell.py`: getting-started-dev.html#try-out-the-translator
.. _JIT: jit/index.html
.. _`JIT Generation in PyPy`: jit/index.html
.. _`just-in-time compiler generator`: jit/index.html
.. _rtyper: rtyper.html
.. _`low-level type system`: rtyper.html#low-level-type
.. _`object-oriented type system`: rtyper.html#oo-type
.. _`garbage collector`: garbage_collection.html
.. _`main PyPy-translation scripts`: getting-started-python.html#translating-the-pypy-python-interpreter
.. _`.NET`: http://www.microsoft.com/net/
.. _Mono: http://www.mono-project.com/
.. _`"standard library"`: rlib.html
.. _`graph viewer`: getting-started-dev.html#try-out-the-translator


.. The following documentation is important and reasonably up-to-date:

.. extradoc: should this be integrated one level up: dcolish?


.. toctree::
   :maxdepth: 1
   :hidden:

   getting-started.rst
   getting-started-python.rst
   getting-started-dev.rst
   windows.rst
   faq.rst
   commandline_ref.rst
   architecture.rst
   coding-guide.rst
   cpython_differences.rst
   garbage_collection.rst
   gc_info.rst
   interpreter.rst
   objspace.rst
   __pypy__-module.rst
   objspace-proxies.rst
   config/index.rst

   dev_method.rst
   extending.rst

   extradoc.rst
   video-index.rst

   glossary.rst

   contributor.rst

   interpreter-optimizations.rst
   configuration.rst
   parser.rst
   rlib.rst
   rtyper.rst
   rffi.rst
   
   translation.rst
   jit/index.rst
   jit/overview.rst
   jit/pyjitpl5.rst

   index-of-release-notes.rst

   ctypes-implementation.rst

   how-to-release.rst

   index-report.rst

   stackless.rst
   sandbox.rst

   discussions.rst

   cleanup.rst

   sprint-reports.rst

   eventhistory.rst
   statistic/index.rst

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
* :ref:`glossary`


.. include:: _ref.txt
