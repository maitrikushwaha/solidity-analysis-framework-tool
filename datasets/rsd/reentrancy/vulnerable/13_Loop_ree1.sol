pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;


    function payAll(address[] memory recipients) public {
        for (uint i = 0; i < recipients.length; ++i) {
            address r = recipients[i];
            require(balances[r] > 0, "Insufficient funds");
            (bool success, ) = r.call{value:balances[r]}("");
            require(success, "Call failed");
            balances[r] = 0; // side-effect after external call
        }
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}