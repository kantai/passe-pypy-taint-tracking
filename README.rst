=====================================
PyPy: Python in Python Implementation 
=====================================

Welcome to PyPy!

PyPy is both an implementation of the Python programming language, and
an extensive compiler framework for dynamic language implementations.
You can build self-contained Python implementations which execute
independently from CPython.

The home page is:

    http://pypy.org/

The getting-started document will help guide you:

    http://doc.pypy.org/en/latest/getting-started.html

It will also point you to the rest of the documentation which is generated
from files in the pypy/doc directory within the source repositories. Enjoy
and send us feedback!

    the pypy-dev team <pypy-dev@python.org>

=====================================
PyPy-Tainting
=====================================

This all comes more or less from here: 

     http://doc.pypy.org/en/latest/getting-started-python.html 

There's two ways you'll be interested in running pypy, with and
without compiling. Compilation takes a while (~1 hour on my laptop)
and requires valid rpython, so to start with, you'll probably just
want to run without compilation. 

Running without Compilation
---------------------------

cd pypy
python bin/pyinteractive.py

This will be slow, and a lot of "C modules" won't work.

Compiling PyPy without JIT
--------------------------

This compiles without JIT but with full optimizations

cd pypy/goal
python ../../rpython/bin/rpython --opt=2 targetpypystandalone.py

Testing it out
--------------

Once you have the pypy prompt, you can test out the tainting code by importing __pypy__.taint (this API is implemented in pypy/modules/__pypy__/interp_taint.py)

so you can test out propagation of data-flows as follows:

   from __pypy__ import taint as t

   a = "A"
   t.add_taint(a, 1)
   b = a.lower()
   t.get_taint(b) # should output [1]
   
   print t.get_control_taint() # should also output [] 

   if a == "A":
      print t.get_control_taint() # should also output [1]

