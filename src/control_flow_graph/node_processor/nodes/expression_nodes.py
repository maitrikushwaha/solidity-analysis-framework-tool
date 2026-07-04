'''
Expression-level AST node types used in Solidity >= 0.5 that were
missing from the original framework.

TupleExpression — (a, b) = foo() or (x + y)
IndexAccess     — arr[idx] or mapping[key]

These are expression nodes (like Identifier, BinaryOperation, etc.)
and do not produce their own CFG edges — they are parsed as metadata
of their parent ExpressionStatement / Assignment / etc.
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class TupleExpression(Node):
    '''
    TupleExpression Node — (expr, expr, ...)
    '''

    def __init__(self, ast_node, entry_node_id, prev_node_id,
                 exit_node_id, cfg_metadata):
        super().__init__(ast_node, entry_node_id, prev_node_id,
                         exit_node_id, cfg_metadata)
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'TupleExpression'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        self.components = []
        for comp in ast_node.get('components', []):
            if comp is None:
                self.components.append(None)
                continue
            comp_type = comp.get('nodeType')
            comp_class = getattr(nodes, comp_type, None) if comp_type else None
            if comp_class:
                self.components.append(
                    comp_class(comp, None, None, None, cfg_metadata))
            else:
                self.components.append(None)

        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self):
        return self.leaves

    def get_whois_next_node(self):
        return self.cfg_id


class IndexAccess(Node):
    '''
    IndexAccess Node — base[index]
    '''

    def __init__(self, ast_node, entry_node_id, prev_node_id,
                 exit_node_id, cfg_metadata):
        super().__init__(ast_node, entry_node_id, prev_node_id,
                         exit_node_id, cfg_metadata)
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'IndexAccess'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        # Parse base expression
        base_ast = ast_node.get('baseExpression', {})
        base_type = base_ast.get('nodeType') if base_ast else None
        base_class = getattr(nodes, base_type, None) if base_type else None
        self.base_expression = (
            base_class(base_ast, None, None, None, cfg_metadata)
            if base_class else None
        )

        # Parse index expression
        idx_ast = ast_node.get('indexExpression', {})
        idx_type = idx_ast.get('nodeType') if idx_ast else None
        idx_class = getattr(nodes, idx_type, None) if idx_type else None
        self.index_expression = (
            idx_class(idx_ast, None, None, None, cfg_metadata)
            if idx_class else None
        )

        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self):
        return self.leaves

    def get_whois_next_node(self):
        return self.cfg_id