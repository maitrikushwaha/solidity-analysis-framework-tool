'''
The Node Processor Sub-module

Provides logic for node types and their class methods.
Also contains the logic to traverse the AST to generate the CFG.
'''
from enum import Enum
from typing import Union
from collections import defaultdict
from graphviz import Digraph


class BasicBlockTypes(Enum):
    '''
    Basic Block Types Enum Definition
    '''
    Entry = 'Entry_Block'
    Exit = 'Exit_Block'

    Statement = 'Statement_Block'
    FunctionBody = 'FunctionBody_Block'
    ClassBody = 'ClassBody_Block'

    Conditional = 'Conditional_Block'
    Loop = 'LoopBlock'
    Branch = 'Branch_Block'

    FunctionCall = 'FunctionCall_Block'


class ExtraNodes(Enum):
    CN_F = 'ForLoop_Condition'
    CN_W = 'WhileLoop_Condition'
    CN_DW = 'DoWhileLoop_Condition'

    JN_F = 'ForLoop_Join'
    JN_W = 'WhileLoop_Join'
    JN_DW = 'DoWhileLoop_Join'
    JN_IF = 'IfCOndition_Join'

    EN_SOURCE = 'SourceUnit_Entry'
    EN_DW = 'DoWhileLoop_Entry'
    EN_FN = 'FunctionBody_Entry'

    EX_FN = 'FunctionBody_Exit'
    EX_SOURCE = 'SourceUnit_Exit'


class NodeInterface(object):
    '''
    Interface for nodes
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata):
        '''
        Constructor
        '''

        raise NotImplementedError

    def add_prev_node(self, node_id: str, label=None, extra_data=None) -> None:
        '''
        Method to add previous node's id
        '''

        raise NotImplementedError

    def add_next_node(self, node_id: str, label=None, extra_data=None) -> None:
        '''
        Method to add next node's id
        '''

        raise NotImplementedError

    def set_entry_node(self, node_id: str) -> None:
        '''
        Set node id of the entry node
        '''

        raise NotImplementedError

    def set_exit_node(self, node_id: str) -> None:
        '''
        Set node id of the exit node
        '''

        raise NotImplementedError

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''

        raise NotImplementedError

    def get_whois_next_node(self) -> str:
        '''
        Get who is the next node for their node id
        For nodes like for or while loops,
        nodes like the continue and initialiation statement become the next node, 
        instead of the loop statement / condition node.

        This method handles such special cases where the next node might not exactly be the node itself, 
        but rather some special node of that node's block
        '''

        raise NotImplementedError


class CFGMetadata(object):
    '''
    Metadata Container Class Definition
    '''

    def __init__(self):
        # this contains the mapping of Node ID to node object
        self.node_table = dict()

        # this contains the mapping of node type to
        # the count of that type of nodes
        self.node_count = defaultdict(int)

        # create a symbol table for variables and constants with their types
        self.variable_table = dict()

    def register_node(self, node_pointer: NodeInterface, node_type: str) -> str:
        '''
        Register and Return the Node's Given ID
        '''

        # generate the node id (starts from 0)
        node_id = f'{node_type}_{self.node_count[node_type]}'

        # and increment the node type count
        self.node_count[node_type] += 1

        # add the node object to the mapping table
        self.node_table[node_id] = node_pointer

        # return the node id
        return node_id

    def get_node(self, node_id: str) -> Union[NodeInterface, None]:
        '''
        Get the Node object from the node ID
        '''

        return self.node_table.get(node_id, None)

    def register_variable(self, var_name: str, var_type: str) -> None:
        '''
        Register and Return the Node's Given ID
        '''

        # set the variable and it's type
        self.variable_table[var_name] = var_type

    def get_var_type(self, var_name: str) -> str:
        '''
        Get the Variable and its Type
        '''

        return self.variable_table.get(var_name, None)
    def get_all_nodes(self):
        '''
        Return all nodes as a dictionary
        '''
        return self.node_table

    def get_node_by_ast_id(self, ast_id):
        for node in self.node_table.values():
            if getattr(node, 'ast_id', None) == ast_id:
                return node
        return None

class Node(NodeInterface):
    '''
    Base class for nodes
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''

        _ = prev_node_id

        # init leaves set
        self.leaves = set()

        # the cfg metadata object
        self.cfg_metadata = cfg_metadata

        # the cfg id object
        self.cfg_id = None

        # set the entry node and the exit node
        # entry node is start (global) and exit node is end (global)
        self.entry_node = entry_node_id
        self.exit_node = exit_node_id
        self.join_node = None
        self.condition_node = None

        # init next nodes as a list of node ids
        # same goes for previous nodes, but we initially add the previous_node
        # here previous node is the one from which we call this node's constructor
        self.next_nodes = dict()
        self.prev_nodes = dict()

        # set the source map in the form (s:l:i)
        # s = start index, l = length, i = index
        self.src_map = (int(i) for i in ast_node['src'].split(':')) \
            if 'src' in ast_node else None

        # set the ast id, if available
        self.ast_id = ast_node.get('id', None)

        # set the children nodes from the AST node information
        self.children = ast_node.get('nodes', list())

    def add_prev_node(self, node_id: str, label=None, extra_data=None) -> None:
        '''
        Method to add previous node's id
        '''

        if node_id is None:
            return

        self.prev_nodes[node_id] = {
            'label': label,
            'extra_data': extra_data
        }

    def add_next_node(self, node_id: str, label=None, extra_data=None, _internal=False) -> None:
        '''
        Method to add next node's id
        '''
        if node_id is None:
            return

        # get the whois next node, or skip it if internal call
        node_for_next = node_id
        if not _internal:
            # get the node instance and check for any condition nodes
            node = self.cfg_metadata.get_node(node_id)
            node_for_next = node.get_whois_next_node()

        self.next_nodes[node_for_next] = {
            'label': label,
            'extra_data': extra_data
        }

    def set_entry_node(self, node_id: str) -> None:
        '''
        Set node id of the entry node
        '''

        self.entry_node = node_id

    def set_exit_node(self, node_id: str) -> None:
        '''
        Set node id of the exit node
        '''

        self.exit_node = node_id

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''
        print(f"[DEBUG] get_leaf_nodes not implemented for {self.__class__.__name__}")
        raise NotImplementedError


    def get_whois_next_node(self) -> str:
        '''
        Get who is the next node for their node id
        For nodes like for or while loops,
        nodes like the continue and initialiation statement become the next node, 
        instead of the loop statement / condition node.

        This method handles such special cases where the next node might not exactly be the node itself, 
        but rather some special node of that node's block
        '''

        return self.cfg_id
