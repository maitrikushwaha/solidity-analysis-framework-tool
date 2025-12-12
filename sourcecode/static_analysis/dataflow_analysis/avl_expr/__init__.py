'''
The Available Expression DataFlow Analysis
'''
from typing import Union
from control_flow_graph import ControlFlowGraph
from static_analysis.dataflow_analysis.avl_expr.expr_builder import expr_builder
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import Expression, ExpressionStatement


class AvailableExpressionAnalysis(object):
    '''
    Class defining the available expression data flow analysis
    '''

    def __init__(self, cfg: ControlFlowGraph, starting_node: str, ending_node: str):
        '''
        Constructor
        '''

        self.cfg = cfg
        self.starting_node = starting_node
        self.ending_node = ending_node

        self.GEN = dict()
        self.KILL = dict()

        self.ENTRY = dict()
        self.EXIT = dict()

        self.expr_table = dict()
        self.node_expr_table = dict()

    def set_node_expr(self, node_id: str, expr: ExpressionStatement) -> None:
        '''
        Add Node's ExpressionStatement to the table
        '''

        self.node_expr_table[node_id] = expr

    def get_node_expr(self, node_id: str) -> ExpressionStatement:
        '''
        Get Node's ExpressionStatement from the table
        '''

        return self.node_expr_table[node_id] if node_id in self.node_expr_table else None

    def set_expr(self, expr_str: str, symbols: set) -> None:
        '''
        Add Expression to expression table
        '''

        expr = Expression(expr_str, symbols)

        self.expr_table[expr.expression] = expr

    def get_expr(self, expr_str: str) -> Expression:
        '''
        Get Expression from expression table
        '''

        return self.expr_table[expr_str]

    def get_exprs_with_symbol(self, symbol: str) -> str:
        '''
        Get Expression(s) having symbol from expression table
        '''

        list_of_expressions = []
        for _, expr in self.expr_table.items():
            if symbol in expr.symbols:
                list_of_expressions.append(expr.expression)

        return list_of_expressions

    def add_gen(self, node_id: str, expr_str: str) -> None:
        '''
        Add GEN record for a node
        '''
        if node_id not in self.GEN:
            self.GEN[node_id] = set()

        self.GEN[node_id].add(expr_str)

    def get_gen(self, node_id: str) -> set:
        '''
        get gen record for a node
        '''
        if node_id not in self.GEN:
            self.GEN[node_id] = set()

        return self.GEN[node_id]

    def add_kill(self, node_id: str, expr_str: str) -> None:
        '''
        Add KILL record for a node
        '''
        if node_id not in self.KILL:
            self.KILL[node_id] = set()

        self.KILL[node_id].add(expr_str)

    def get_kill(self, node_id: str) -> set:
        '''
        get kills record for a node
        '''
        if node_id not in self.KILL:
            self.KILL[node_id] = set()

        return self.KILL[node_id]

    def add_entry(self, node_id: str, exprs: Union[str, set]) -> None:
        '''
        Add entry record for a node
        '''
        if node_id not in self.ENTRY:
            self.ENTRY[node_id] = set()

        if isinstance(exprs, set):
            self.ENTRY[node_id].update(exprs)
        else:
            self.ENTRY[node_id].add(exprs)

    def get_entry(self, node_id: str) -> set:
        '''
        get entry record for a node
        '''
        if node_id not in self.ENTRY:
            self.ENTRY[node_id] = set()

        return self.ENTRY[node_id]

    def add_exit(self, node_id: str, exprs: Union[str, set]) -> None:
        '''
        Add exit record for a node
        '''
        if node_id not in self.EXIT:
            self.EXIT[node_id] = set()

        if isinstance(exprs, set):
            self.EXIT[node_id].update(exprs)
        else:
            self.EXIT[node_id].add(exprs)

    def get_exit(self, node_id: str) -> set:
        '''
        get exit record for a node
        '''
        if node_id not in self.EXIT:
            self.EXIT[node_id] = set()

        return self.EXIT[node_id]

    def compute(self) -> None:
        '''
        Compute the available expression data flow analysis
        '''

        self.__compute_expressions()
        print(self.expr_table.keys())

        self.__compute_gen_kill()
        print(self.GEN)
        print(self.KILL)

        self.__compute_avl_expr()
        print(self.ENTRY)
        print(self.EXIT)

    def __compute_expressions(self) -> None:
        '''
        Compute and enroll all the expressions present in the CFG
        '''

        visited = set()

        def traverse(node_id, visited: set, cfg: ControlFlowGraph):
            '''
            Traverse the Graph and Compute the GEN and KILL functions
            '''

            if node_id in visited:
                return

            # add to visited set
            visited.add(node_id)

            # get node instance / object
            node = cfg.cfg_metadata.get_node(node_id)

            # build the expression, if available
            expr = expr_builder(node)

            # register the expressions
            if expr is not None:
                self.set_node_expr(node_id, expr)
                if len(expr.right_symbols) > 0:
                    self.set_expr(expr.right_str, expr.right_symbols)

            print("EXPR-SEARCH", node_id)

            if node_id != self.ending_node:
                for child_id in node.next_nodes:
                    child_node = cfg.cfg_metadata.get_node(child_id)

                    traverse(child_node.cfg_id, visited, cfg)

        traverse(self.starting_node, visited, self.cfg)

    def __compute_gen_kill(self) -> None:
        '''
        Compute the GEN and KILL functions for all the nodes
        '''

        visited = set()

        def traverse(node_id, visited: set, cfg: ControlFlowGraph):
            '''
            Traverse the Graph and Compute the GEN and KILL functions
            '''

            if node_id in visited:
                return

            # add to visited set
            visited.add(node_id)

            # get node instance / object
            node = cfg.cfg_metadata.get_node(node_id)

            # retrieve the expression, if available
            expr = self.get_node_expr(node_id)

            ###########################
            # compute the generates set
            # if there are right symbols present, and no right symbol is present in the left side
            # if a symbol from the right side is present in the left side, this means, it is writing after generation
            # in that case the generated set will be empty
            if expr is not None:
                if len(expr.right_symbols) > 0 and len(expr.right_symbols.intersection(expr.left_symbols)) == 0:
                    self.add_gen(node_id, expr.right_str)

            ###########################
            # compute the kills set
            if expr is not None:
                for symbol in expr.left_symbols:
                    for expression in self.get_exprs_with_symbol(symbol):
                        self.add_kill(node_id, expression)

            print("GEN-KILL", node_id)

            if node_id != self.ending_node:
                for child_id in node.next_nodes:
                    child_node = cfg.cfg_metadata.get_node(child_id)

                    traverse(child_node.cfg_id, visited, cfg)

        traverse(self.starting_node, visited, self.cfg)

    def __compute_avl_expr(self) -> None:
        '''
        Compute the GEN and KILL functions for all the nodes
        '''

        worklist = set()
        visited = set()

        # initialize worklist with initial node
        worklist.add(self.starting_node)

        while len(worklist) != 0:
            node_id = worklist.pop()

            print('WORKLIST PROCESS', node_id)

            entries, exit_set = list(), set()

            node = self.cfg.cfg_metadata.get_node(node_id)

            #######################
            # 1. compute the entry set
            for prev_id in node.prev_nodes:
                entries.append(self.get_exit(prev_id))

            # in this case, we need intersection of all incoming branches
            entry = set.intersection(*entries)

            # finally update the entry set
            self.add_entry(node_id, entry)

            #######################
            # 2. compute the exit set (based on the transfer function)
            exit_set = set.difference(entry, self.get_kill(node_id))
            exit_set = exit_set.union(self.get_gen(node_id))

            #######################
            # 3. if exit set is changed OR node is processed first time,
            # add the next nodes of the node to worklist
            if exit_set != self.get_exit(node_id) or node_id not in visited:
                visited.add(node_id)

                self.add_exit(node_id, exit_set)

                if node_id != self.ending_node:
                    for next_id in node.next_nodes:
                        worklist.add(next_id)
