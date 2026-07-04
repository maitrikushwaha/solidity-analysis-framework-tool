pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    address private target = 0xD591678684E7c2f033b5eFF822553161bdaAd781;    // coin_base

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        (bool success, ) = target.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        balances[msg.sender] = 0; // side-effect after external call
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}