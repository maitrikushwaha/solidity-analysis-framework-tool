pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;


    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        bool success = payable(msg.sender).send(balances[msg.sender]);
        if(!success) revert();
        balances[msg.sender] = 0;
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}