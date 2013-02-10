.. XXX armin, what do we do with this?


Ordering finalizers in the SemiSpace GC
=======================================

Goal
----

After a collection, the SemiSpace GC should call the finalizers on
*some* of the objects that have one and that have become unreachable.
Basically, if there is a reference chain from an object a to an object b
then it should not call the finalizer for b immediately, but just keep b
alive and try again to call its finalizer after the next collection.

This basic idea fails when there are cycles.  It's not a good idea to
keep the objects alive forever or to never call any of the finalizers.
The model we came up with is that in this case, we could just call the
finalizer of one of the objects in the cycle -- but only, of course, if
there are no other objects outside the cycle that has a finalizer and a
reference to the cycle.

More precisely, given the graph of references between objects::

    for each strongly connected component C of the graph:
        if C has at least one object with a finalizer:
            if there is no object outside C which has a finalizer and
            indirectly references the objects in C:
                mark one of the objects of C that has a finalizer
                copy C and all objects it references to the new space

    for each marked object:
        detach the finalizer (so that it's not called more than once)
        call the finalizer

Algorithm
---------

During deal_with_objects_with_finalizers(), each object x can be in 4
possible states::

    state[x] == 0:  unreachable
    state[x] == 1:  (temporary state, see below)
    state[x] == 2:  reachable from any finalizer
    state[x] == 3:  alive

Initially, objects are in state 0 or 3 depending on whether they have
been copied or not by the regular sweep done just before.  The invariant
is that if there is a reference from x to y, then state[y] >= state[x].

The state 2 is used for objects that are reachable from a finalizer but
that may be in the same strongly connected component than the finalizer.
The state of these objects goes to 3 when we prove that they can be
reached from a finalizer which is definitely not in the same strongly
connected component.  Finalizers on objects with state 3 must not be
called.

Let closure(x) be the list of objects reachable from x, including x
itself.  Pseudo-code (high-level) to get the list of marked objects::

    marked = []
    for x in objects_with_finalizers:
        if state[x] != 0:
            continue
        marked.append(x)
        for y in closure(x):
            if state[y] == 0:
                state[y] = 2
            elif state[y] == 2:
                state[y] = 3
    for x in marked:
        assert state[x] >= 2
        if state[x] != 2:
            marked.remove(x)

This does the right thing independently on the order in which the
objects_with_finalizers are enumerated.  First assume that [x1, .., xn]
are all in the same unreachable strongly connected component; no object
with finalizer references this strongly connected component from
outside.  Then:

* when x1 is processed, state[x1] == .. == state[xn] == 0 independently
  of whatever else we did before.  So x1 gets marked and we set
  state[x1] = .. = state[xn] = 2.

* when x2, ... xn are processed, their state is != 0 so we do nothing.

* in the final loop, only x1 is marked and state[x1] == 2 so it stays
  marked.

Now, let's assume that x1 and x2 are not in the same strongly connected
component and there is a reference path from x1 to x2.  Then:

* if x1 is enumerated before x2, then x2 is in closure(x1) and so its
  state gets at least >= 2 when we process x1.  When we process x2 later
  we just skip it ("continue" line) and so it doesn't get marked.

* if x2 is enumerated before x1, then when we process x2 we mark it and
  set its state to >= 2 (before x2 is in closure(x2)), and then when we
  process x1 we set state[x2] == 3.  So in the final loop x2 gets
  removed from the "marked" list.

I think that it proves that the algorithm is doing what we want.

The next step is to remove the use of closure() in the algorithm in such
a way that the new algorithm has a reasonable performance -- linear in
the number of objects whose state it manipulates::

    marked = []
    for x in objects_with_finalizers:
        if state[x] != 0:
            continue
        marked.append(x)
        recursing on the objects y starting from x:
            if state[y] == 0:
                state[y] = 1
                follow y's children recursively
            elif state[y] == 2:
                state[y] = 3
                follow y's children recursively
            else:
                don't need to recurse inside y
        recursing on the objects y starting from x:
            if state[y] == 1:
                state[y] = 2
                follow y's children recursively
            else:
                don't need to recurse inside y
    for x in marked:
        assert state[x] >= 2
        if state[x] != 2:
            marked.remove(x)

In this algorithm we follow the children of each object at most 3 times,
when the state of the object changes from 0 to 1 to 2 to 3.  In a visit
that doesn't change the state of an object, we don't follow its children
recursively.

In practice, in the SemiSpace, Generation and Hybrid GCs, we can encode
the 4 states with a single extra bit in the header:

      =====  =============  ========  ====================
      state  is_forwarded?  bit set?  bit set in the copy?
      =====  =============  ========  ====================
        0      no             no        n/a
        1      no             yes       n/a
        2      yes            yes       yes
        3      yes          whatever    no
      =====  =============  ========  ====================

So the loop above that does the transition from state 1 to state 2 is
really just a copy(x) followed by scan_copied().  We must also clear the
bit in the copy at the end, to clean up before the next collection
(which means recursively bumping the state from 2 to 3 in the final
loop).

In the MiniMark GC, the objects don't move (apart from when they are
copied out of the nursery), but we use the flag GCFLAG_VISITED to mark
objects that survive, so we can also have a single extra bit for
finalizers:

      =====  ==============  ============================
      state  GCFLAG_VISITED  GCFLAG_FINALIZATION_ORDERING
      =====  ==============  ============================
        0        no              no
        1        no              yes
        2        yes             yes
        3        yes             no
      =====  ==============  ============================
