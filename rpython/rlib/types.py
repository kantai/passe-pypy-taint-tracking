from rpython.annotator import model
from rpython.annotator.listdef import ListDef
from rpython.annotator.dictdef import DictDef


def none():
    return model.s_None


def float():
    return model.SomeFloat()

def singlefloat():
    return model.SomeSingleFloat()

def longfloat():
    return model.SomeLongFloat()


def int():
    return model.SomeInteger()


def unicode():
    return model.SomeUnicodeString()

def unicode0():
    return model.SomeUnicodeString(no_nul=True)

def str():
    return model.SomeString()

def str0():
    return model.SomeString(no_nul=True)

def char():
    return model.SomeChar()


def ptr(ll_type):
    from rpython.rtyper.lltypesystem.lltype import Ptr
    return model.SomePtr(Ptr(ll_type))


def list(element):
    listdef = ListDef(None, element, mutated=True, resized=True)
    return model.SomeList(listdef)

def array(element):
    listdef = ListDef(None, element, mutated=True, resized=False)
    return model.SomeList(listdef)

def dict(keytype, valuetype):
    dictdef = DictDef(None, keytype, valuetype)
    return model.SomeDict(dictdef)


def instance(class_):
    return lambda bookkeeper: model.SomeInstance(bookkeeper.getuniqueclassdef(class_))

class SelfTypeMarker(object):
    pass

def self():
    return SelfTypeMarker()
