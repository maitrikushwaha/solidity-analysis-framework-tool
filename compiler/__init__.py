'''
SADA
'''
import solcx
from typing import Union
from compiler.solc_selector import SolcSelector
from compiler.output_generator import CompiledOutputGenerator


class SolCompiler(object):

    def __init__(self, source_code: str):
        self.source_code = source_code

        solc_selector = SolcSelector()
        solidity_pragma = self.extract_pragma(source_code)
        self.solidity_version = solc_selector.install_solc_pragma_solc(
            solidity_pragma)

        solcx.set_solc_version(self.solidity_version)

    def compile(self):
        self.compiled_output = CompiledOutputGenerator(self.source_code)
        return self.compiled_output

    @staticmethod
    def extract_pragma(source_code: str) -> Union[str, None]:
        '''
        Extract the Solidity Version Pragma from the source code
        '''
        for line_text in source_code.split('\n'):
            if line_text.startswith('pragma solidity'):
                return line_text
        return None
