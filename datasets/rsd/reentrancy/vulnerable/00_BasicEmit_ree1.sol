pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    event Transfer(uint256 amt);

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        emit Transfer(balances[msg.sender]);
        balances[msg.sender] = 0; // side-effect after external call
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}