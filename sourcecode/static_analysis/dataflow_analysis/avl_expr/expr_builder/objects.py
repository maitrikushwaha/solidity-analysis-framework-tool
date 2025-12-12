class ExpressionStatement(object):
    '''
    The expression statement object class
    '''

    def __init__(self, expr_str: str, left_str: str, right_str: str, left_symbols: set, right_symbols: set):
        '''
        constructor
        '''

        self.expression = expr_str

        self.left_str = left_str
        self.right_str = right_str

        self.left_symbols = left_symbols
        self.right_symbols = right_symbols


class Expression(object):
    '''
    The expression object class
    '''

    def __init__(self, expr_str: str, symbols: set):
        '''
        constructor
        '''

        self.expression = expr_str

        self.symbols = symbols
