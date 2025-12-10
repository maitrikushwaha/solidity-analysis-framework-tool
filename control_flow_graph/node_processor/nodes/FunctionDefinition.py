'''
Class definition for the Function Definition CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import Node, BasicBlockTypes
import control_flow_graph.node_processor.nodes as nodes
from control_flow_graph.node_processor.nodes.extra_nodes.function.entry import FunctionEntry
from control_flow_graph.node_processor.nodes.extra_nodes.function.exit import FunctionExit


class FunctionDefinition(Node):
    '''
    Function Definition Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(FunctionDefinition, self).__init__(ast_node, entry_node_id, prev_node_id,
                                                 exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.FunctionBody
        self.node_type = 'FunctionDefinition'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.documentation = ast_node.get('documentation', None)
        self.implemented = ast_node.get('implemented', None)
        self.isConstructor = ast_node.get('isConstructor', None)
        self.isDeclaredConst = ast_node.get('isDeclaredConst', None)
        self.modifiers = ast_node.get('modifiers', list())
        self.parameters = ast_node.get('parameters', dict())
        self.returnParameters = ast_node.get('returnParameters', dict())
        self.payable = ast_node.get('payable', None)
        self.stateMutability = ast_node.get('stateMutability', None)
        self.superFunciton = ast_node.get('superFunction', None)
        self.visibility = ast_node.get('visibility', None)
        self.name = ast_node.get('name', None)
        self.scope = ast_node.get('scope', None)

        # create the function entry node and
        # add the node to the next_nodes list
        function_entry = FunctionEntry(dict(), self.entry_node, self.cfg_id,
                                       None, cfg_metadata)
        self.add_next_node(function_entry.cfg_id)

        # create the exit node for the function and
        # link the exit function to the exit of the source unit
        function_exit = FunctionExit(dict(), function_entry.cfg_id, None,
                                     self.exit_node, cfg_metadata)

        # perform logic to create the body of the function
        self.children = []

        if ast_node['body'] is None:
            # Interface or abstract function, skip CFG generation
            return

        body_statements = ast_node['body']['statements']
        body_prev_statement = function_entry.cfg_id
        for i, statement in enumerate(body_statements):
            # obtain the child node's type
            child_node_type = statement['nodeType']

            print(child_node_type)

            # obtain the child node's constructor
            childConstructor = getattr(nodes, child_node_type, Node)

            # initialize the child node (recursive)
            child_node = childConstructor(statement,
                                          function_entry.cfg_id, body_prev_statement,
                                          function_exit.cfg_id, cfg_metadata)

            self.children.append(child_node)

            # also link the previous statement in the block with the current statement
            # 1. first obtain the prev node's leaves
            prev_leaves = self.cfg_metadata.get_node(
                body_prev_statement).get_leaf_nodes()

            # 2. now check if the leaf node is there or we need to link the previous node itself
            to_link = body_prev_statement if len(
                prev_leaves) == 0 else next(iter(prev_leaves))

            # 3. link the leaf node's next as the child node
            self.cfg_metadata.get_node(
                to_link).add_next_node(child_node.cfg_id)

            # add the child node's ID to the next_nodes list
            body_prev_statement = child_node.cfg_id if child_node.join_node is None else child_node.join_node

            # if it is the last node in the statements block,
            # them we needto obtain the leaf nodes of this one,
            # and link their next as the exit node of the function
            if i == len(body_statements) - 1:
                self.leaves.update(child_node.get_leaf_nodes())

        # pop the leaf node
        last_stmt_node = self.leaves.pop()

        # set the previous node of the exit node as the last statement of the body
        function_exit.add_prev_node(last_stmt_node)

        # also add the next node of last child as the exit node
        cfg_metadata.get_node(
            last_stmt_node).add_next_node(function_exit.cfg_id)

        # finally, add the function exit as the leaf of the function
        self.leaves.add(function_exit.cfg_id)
       
        FunctionDefinition._assign_enclosing_function_static(function_entry, self)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''

        return self.leaves
    
    # --- Helper function to annotate enclosing_function ---
    @staticmethod
    def _assign_enclosing_function_static(start_node, func_def):
        """
        Assigns enclosing_function for all nodes reachable from the function entry.
        """
        to_visit = [start_node]
        visited = set()

        while to_visit:
            current = to_visit.pop()
            if current in visited:
                continue
            visited.add(current)

            current.enclosing_function = func_def

            # Explore all direct next nodes
            if hasattr(current, "next_nodes"):
                for next_id in current.next_nodes:
                    next_node = func_def.cfg_metadata.get_node(next_id)
                    if next_node and next_node not in visited:
                        to_visit.append(next_node)

            # Also consider children (for nested/compound structures)
            if hasattr(current, "children"):
                for child in current.children:
                    if child and child not in visited:
                        to_visit.append(child)
