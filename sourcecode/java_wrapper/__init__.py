import jpype
import os

# Ensure JVM is started with the correct classpath and library path
def start_apron_jvm():
    jar_path_apron = "/home/maitri/apron/japron/apron.jar"
    jar_path_gmp = "/home/maitri/apron/japron/gmp.jar"
    so_path = "/home/maitri/apron/japron"

    # Set LD_LIBRARY_PATH to include the directory containing libjgmp.so and libjapron.so
    lib_path = "/home/maitri/apron/japron"
    
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
