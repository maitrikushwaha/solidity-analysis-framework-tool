import logging
'''
Class definition for the TryStatement CFG (AST) node.

Solidity >= 0.6 `try expr { ... } catch { ... }` blocks.
This handler processes the success body and each catch clause
as separate branches, similar to IfStatement.
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class TryStatement(Node):
    '''
    TryStatement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        super(TryStatement, self).__init__(
            ast_node, entry_node_id, prev_node_id,
            exit_node_id, cfg_metadata)

        self.basic_block_type = BasicBlockTypes.Conditional
        self.node_type = 'TryStatement'
        self.add_prev_node(prev_node_id)
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        logging.debug(f'Processing CFG Node {self.cfg_id}')

        # Process all clauses (success + catch blocks)
        # Each clause has a 'block' with 'statements'
        self._clause_nodes = []
        clauses = ast_node.get('clauses', [])

        for clause in clauses:
            block = clause.get('block', {})
            stmts = block.get('statements', [])
            clause_prev = self.cfg_id
            clause_children = []

            for j, stmt in enumerate(stmts):
                stmt_type = stmt['nodeType']
                ctor = getattr(nodes, stmt_type, Node)
                child = ctor(stmt, entry_node_id, clause_prev,
                             exit_node_id, cfg_metadata)
                clause_children.append(child)

                if j == 0:
                    self.add_next_node(child.cfg_id)
                else:
                    prev_obj = self.cfg_metadata.get_node(clause_prev)
                    if prev_obj is not None:
                        prev_leaves = prev_obj.get_leaf_nodes()
                        to_link = (clause_prev if not prev_leaves
                                   else next(iter(prev_leaves)))
                        link_obj = self.cfg_metadata.get_node(to_link)
                        if link_obj is not None:
                            link_obj.add_next_node(child.cfg_id)

                clause_prev = (child.cfg_id if child.join_node is None
                               else child.join_node)

            if clause_children:
                self.leaves.update(clause_children[-1].get_leaf_nodes())
            self._clause_nodes.extend(clause_children)

        if not self.leaves:
            self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        child_leaves = set()
        for node_id in self.next_nodes.keys():
            node = self.cfg_metadata.get_node(node_id)
            if node is not None:
                child_leaves.update(node.get_leaf_nodes())
        if child_leaves:
            self.leaves = set(child_leaves)
        return self.leaves

    def get_whois_next_node(self) -> str:
        return self.cfg_id