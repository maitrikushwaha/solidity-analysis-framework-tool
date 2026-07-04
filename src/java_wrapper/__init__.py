import jpype
import os

# Ensure JVM is started with the correct classpath and library path.
# The APRON/japron install directory is configurable via the APRON_HOME
# environment variable; it defaults to ~/apron/japron (resolved at runtime, so
# no machine-specific absolute path is hard-coded in the source).
def start_apron_jvm():
    apron_home = os.environ.get("APRON_HOME", os.path.expanduser("~/apron/japron"))

    jar_path_apron = os.path.join(apron_home, "apron.jar")
    jar_path_gmp = os.path.join(apron_home, "gmp.jar")
    so_path = apron_home

    # Directory containing libjgmp.so and libjapron.so
    lib_path = apron_home

    # Make sure to include all shared libraries required
    os.environ['LD_LIBRARY_PATH'] = f"{lib_path}:" + os.environ.get('LD_LIBRARY_PATH', '')

    # Check if the JVM is already started
    if not jpype.isJVMStarted():
        jpype.startJVM(jpype.getDefaultJVMPath(),
                       "-Djava.class.path={}:{}".format(jar_path_apron, jar_path_gmp),
                       "-Djava.library.path={}".format(so_path))

# Start the JVM
start_apron_jvm()

class apron(object):
    '''
    Apron Wrapper Class
    '''

    Abstract0 = jpype.JClass("apron.Abstract0")
    Manager = jpype.JClass("apron.Manager")
    Interval = jpype.JClass("apron.Interval")
    Box = jpype.JClass("apron.Box")
    Octagon = jpype.JClass("apron.Octagon")
    Polka = jpype.JClass("apron.Polka")
    ApronException = jpype.JClass("apron.ApronException")
    MpqScalar = jpype.JClass("apron.MpqScalar")
    Linterm0 = jpype.JClass("apron.Linterm0")
    Linexpr0 = jpype.JClass("apron.Linexpr0")
    Texpr0BinNode = jpype.JClass("apron.Texpr0BinNode")
    Texpr0CstNode = jpype.JClass("apron.Texpr0CstNode")
    Texpr0Node = jpype.JClass("apron.Texpr0Node")
    Texpr0Intern = jpype.JClass("apron.Texpr0Intern")
    Texpr0DimNode = jpype.JClass("apron.Texpr0DimNode")


class java(object):
    '''
    Java Utilities Wrapper Class
    '''

    Arrays = jpype.JClass("java.util.Arrays")
