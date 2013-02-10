"""
Miscellaneous utilities.
"""

class ThreadLocals:
    """Pseudo thread-local storage, for 'space.threadlocals'.
    This is not really thread-local at all; the intention is that the PyPy
    implementation of the 'thread' module knows how to provide a real
    implementation for this feature, and patches 'space.threadlocals' when
    'thread' is initialized.
    """
    _value = None

    def getvalue(self):
        return self._value

    def setvalue(self, value):
        self._value = value

    def ismainthread(self):
        return True

    def getallvalues(self):
        return {0: self._value}
