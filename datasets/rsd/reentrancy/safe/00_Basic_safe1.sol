pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;


    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        balances[msg.sender] = 0;
        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}