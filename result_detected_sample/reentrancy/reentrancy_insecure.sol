/*
 * @source: https://consensys.github.io/smart-contract-best-practices/known_attacks/
 * @author: consensys
 * @vulnerable_at_lines: 17
 */

pragma solidity ^0.5.0;

contract Reentrancy_insecure {

    // INSECURE
    mapping (address => uint) private userBalances;

    function withdrawBalance() public {
        uint amountToWithdraw = userBalances[msg.sender];
        // <yes> <report> REENTRANCY
        (bool success, ) = msg.sender.call.value(amountToWithdraw)(""); // At this point, the caller's code is executed, and can call withdrawBalance again
        require(success);
        userBalances[msg.sender] = 0;
    }
}

// function_call = cfg.cfg_metadata.get_node(
//     'ExpressionStatement_1')
//     # reset next nodes for this statement
//     function_call.next_nodes = dict()
//     function_call.add_next_node('IfStatement_0')
//     cfg.cfg_metadata.get_node('IfStatement_0').add_prev_node(
//     'ExpressionStatement_1')
