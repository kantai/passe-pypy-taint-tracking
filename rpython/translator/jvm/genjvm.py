"""
Backend for the JVM.
"""

from __future__ import with_statement
import os
import re
import subprocess
import sys

import py
from rpython.rtyper.ootypesystem import ootype
from rpython.tool.udir import udir
from rpython.translator.backendopt.all import backend_optimizations
from rpython.translator.backendopt.checkvirtual import check_virtual_methods
from rpython.translator.oosupport.genoo import GenOO
from rpython.translator.translator import TranslationContext

from rpython.translator.jvm.constant import (
    JVMConstantGenerator, JVMStaticMethodConst, JVMCustomDictConst,
    JVMWeakRefConst)
from rpython.translator.jvm.database import Database
from rpython.translator.jvm.generator import JasminGenerator
from rpython.translator.jvm.log import log
from rpython.translator.jvm.node import EntryPoint, Function
from rpython.translator.jvm.opcodes import opcodes
from rpython.translator.jvm.option import getoption
from rpython.translator.jvm.prebuiltnodes import create_interlink_node

MIN_JAVA_VERSION = '1.6.0'

class JvmError(Exception):
    """ Indicates an error occurred in JVM backend """

    def pretty_print(self):
        print str(self)
    pass

class JvmSubprogramError(JvmError):
    """ Indicates an error occurred running some program """
    def __init__(self, res, args, stdout, stderr):
        self.res = res
        self.args = args
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        return "Error code %d running %s" % (self.res, repr(self.args))

    def pretty_print(self):
        JvmError.pretty_print(self)
        print "vvv Stdout vvv\n"
        print self.stdout
        print "vvv Stderr vvv\n"
        print self.stderr


class JvmGeneratedSource(object):

    """
    An object which represents the generated sources. Contains methods
    to find out where they are located, to compile them, and to execute
    them.

    For those interested in the location of the files, the following
    attributes exist:
    tmpdir --- root directory from which all files can be found (py.path obj)
    javadir --- the directory containing *.java (py.path obj)
    classdir --- the directory where *.class will be generated (py.path obj)
    package --- a string with the name of the package (i.e., 'java.util')

    The following attributes also exist to find the state of the sources:
    compiled --- True once the sources have been compiled successfully
    """
    _cached = None

    def __init__(self, tmpdir, package):
        """
        'tmpdir' --- the base directory where the sources are located
        'package' --- the package the sources are in; if package is pypy.jvm,
        then we expect to find the sources in $tmpdir/pypy/jvm
        'jfiles' --- list of files we need to run jasmin on
        """
        self.tmpdir = tmpdir
        self.package = package
        self.compiled = False
        self.jasmin_files = None

        # Determine various paths:
        self.thisdir = py.path.local(__file__).dirpath()
        self.rootdir = self.thisdir.join('src')
        self.srcdir = self.rootdir.join('pypy')
        self.jnajar = self.rootdir.join('jna.jar')
        self.jasminjar = self.rootdir.join('jasmin.jar')

        # Compute directory where .j files are
        self.javadir = self.tmpdir
        for subpkg in package.split('.'):
            self.javadir = self.javadir.join(subpkg)

        # Compute directory where .class files should go
        self.classdir = self.javadir

    def set_jasmin_files(self, jfiles):
        self.jasmin_files = jfiles

    def _invoke(self, args, allow_stderr):
        import sys
        if sys.platform == 'nt':
            shell = True
        else:
            shell = False
        subp = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=shell, universal_newlines=True)
        stdout, stderr = subp.communicate()
        res = subp.wait()
        if res or (not allow_stderr and stderr):
            raise JvmSubprogramError(res, args, stdout, stderr)
        return stdout, stderr, res

    def _compile_helper(self):
        # HACK: compile the Java helper classes.  Should eventually
        # use rte.py
        if JvmGeneratedSource._cached == self.classdir:
           return
        log.red('Compiling java classes')
        javafiles = self.srcdir.listdir('*.java')
        javasrcs = [str(jf) for jf in javafiles]
        self._invoke([getoption('javac'),
                      '-nowarn',
                      '-d', str(self.classdir),
                      '-classpath', str(self.jnajar),
                      ] + javasrcs,
                     True)
        # NOTE if you are trying to add more caching: some .java files
        # compile to several .class files of various names.
        JvmGeneratedSource._cached = self.classdir

    def compile(self):
        """
        Compiles the .java sources into .class files, ready for execution.
        """
        jascmd = [
            getoption('java'),
            '-Djava.awt.headless=true',
            '-jar', str(self.jasminjar),
            '-g',
            '-d',
            str(self.javadir)]

        def split_list(files):
            "Split the files list into manageable pieces"

            # - On Windows 2000, commands in .bat are limited to 2047 chars.
            # - But the 'jasmin' script contains a line like
            #     path_to_jre/java -jar path_to_jasmin/jasmin.jar $*
            # So we limit the length of arguments files to:
            MAXLINE = 1500

            chunk = []
            chunklen = 0
            for f in files:
                # Account for the space between items
                chunklen += len(f) + 1
                if chunklen > MAXLINE:
                    yield chunk
                    chunk = []
                    chunklen = len(f)
                chunk.append(f)
            if chunk:
                yield chunk

        for files in split_list(self.jasmin_files):
            #print "Invoking jasmin on %s" % files
            self._invoke(jascmd + files, False)
            #print "... completed!"

        self.compiled = True
        self._compile_helper()

    def _make_str(self, a):
        if isinstance(a, ootype._string):
            return a._str
        return str(a)

    def execute(self, args):
        """
        Executes the compiled sources in a separate process.  Returns the
        output as a string.  The 'args' are provided as arguments,
        and will be converted to strings.
        """
        assert self.compiled
        strargs = [self._make_str(a) for a in args]
        cmd = [getoption('java'),
               '-Xmx256M', # increase the heapsize so the microbenchmarks run
               '-Djava.awt.headless=true',
               '-cp',
               str(self.javadir)+os.pathsep+str(self.jnajar),
               self.package+".Main"] + strargs
        print "Invoking java to run the code"
        stdout, stderr, retval = self._invoke(cmd, True)
        print "...done!"
        sys.stderr.write(stderr)
        return stdout, stderr, retval

def generate_source_for_function(func, annotation, backendopt=False):

    """
    Given a Python function and some hints about its argument types,
    generates JVM sources that call it and print the result.  Returns
    the JvmGeneratedSource object.
    """

    if hasattr(func, 'im_func'):
        func = func.im_func
    t = TranslationContext()
    ann = t.buildannotator()
    ann.build_types(func, annotation)
    t.buildrtyper(type_system="ootype").specialize()
    if backendopt:
        check_virtual_methods(ootype.ROOT)
        backend_optimizations(t)
    main_graph = t.graphs[0]
    if getoption('view'): t.view()
    if getoption('wd'): tmpdir = py.path.local('.')
    else: tmpdir = udir
    jvm = GenJvm(tmpdir, t, EntryPoint(main_graph, True, True))
    return jvm.generate_source()

_missing_support_programs = None

def detect_missing_support_programs():
    global _missing_support_programs
    if _missing_support_programs is not None:
        if _missing_support_programs:
            py.test.skip(_missing_support_programs)
        return

    def missing(msg):
        global _missing_support_programs
        _missing_support_programs = msg
        py.test.skip(msg)

    for cmd in 'javac', 'java':
        if py.path.local.sysfind(getoption(cmd)) is None:
            missing("%s is not on your path" % cmd)
    if not _check_java_version(MIN_JAVA_VERSION):
        missing('Minimum of Java %s required' % MIN_JAVA_VERSION)
    _missing_support_programs = False

def _check_java_version(version):
    """Determine if java meets the specified version"""
    cmd = [getoption('java'), '-version']
    with open(os.devnull, 'w') as devnull:
        stderr = subprocess.Popen(cmd, stdout=devnull,
                                  stderr=subprocess.PIPE).communicate()[1]
    search = re.search('[\.0-9]+', stderr)
    return search and search.group() >= version

class GenJvm(GenOO):

    """ Master object which guides the JVM backend along.  To use,
    create with appropriate parameters and then invoke
    generate_source().  *You can not use one of these objects more than
    once.* """

    TypeSystem = lambda X, db: db # TypeSystem and Database are the same object
    Function = Function
    Database = Database
    opcodes = opcodes
    log = log

    ConstantGenerator = JVMConstantGenerator
    CustomDictConst   = JVMCustomDictConst
    StaticMethodConst = JVMStaticMethodConst
    WeakRefConst = JVMWeakRefConst

    def __init__(self, tmpdir, translator, entrypoint):
        """
        'tmpdir' --- where the generated files will go.  In fact, we will
        put our binaries into the directory pypy/jvm
        'translator' --- a TranslationContext object
        'entrypoint' --- if supplied, an object with a render method
        """
        GenOO.__init__(self, tmpdir, translator, entrypoint)
        self.jvmsrc = JvmGeneratedSource(tmpdir, getoption('package'))

    def append_prebuilt_nodes(self):
        create_interlink_node(self.db)

    def generate_source(self):
        """ Creates the sources, and returns a JvmGeneratedSource object
        for manipulating them """
        GenOO.generate_source(self)
        self.jvmsrc.set_jasmin_files(self.db.jasmin_files())
        return self.jvmsrc

    def create_assembler(self):
        """ Creates and returns a Generator object according to the
        configuration.  Right now, however, there is only one kind of
        generator: JasminGenerator """
        return JasminGenerator(self.db, self.jvmsrc.javadir)
