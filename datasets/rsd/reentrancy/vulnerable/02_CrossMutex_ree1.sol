pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    bool flag = false;
    mapping (address => uint256) public balances;

    function transfer(address to, uint256 amt) public { //an attacker can reenter here before the side effect on the other function is executed
        require(balances[msg.sender] >= amt, "Insufficient funds");
        balances[to] += amt;
        balances[msg.sender] -= amt;
    }

    function withdraw() public {
        require(!flag, "Locked");
        flag = true;


        require(balances[msg.sender] > 0, "Insufficient funds");
        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        balances[msg.sender] = 0; // side-effect after external call


        flag = false;
    }

    function deposit() public payable {
        require(!flag, "Locked");
        balances[msg.sender] += msg.value;       
    }

}