pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    bool flag = false;
    mapping (address => uint256) public balances;

    function transfer(address to, uint256 amt) public {
        require(!flag, "Locked");
        require(balances[msg.sender] >= amt, "Insufficient funds");
        balances[to] += amt;
        balances[msg.sender] -= amt;
    }

    function withdrawAll() public {
        require(!flag, "Locked");
        flag = true;

        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        balances[msg.sender] = 0; // side-effect after external call

        flag = false;
    }

    function deposit() public payable { // reentering here and calling deposit makes the attacker LOSE some money. This is an inconsistent state
        balances[msg.sender] += msg.value;       
    }

}