pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    bool private flag;

    modifier nonReentrant() {
        require(!flag, "Locked");
        _;
        flag = false;
    }
    
    function transfer(address to, uint256 amt) nonReentrant public {
        require(balances[msg.sender] >= amt, "Insufficient funds");
        balances[to] += amt;
        balances[msg.sender] -= amt;
    }

    function payAll(address[] memory recipients) nonReentrant public {
        for (uint i = 0; i < recipients.length; ++i) {
            address r = recipients[i];
            require(balances[r] > 0, "Insufficient funds");
            (bool success, ) = r.call{value:balances[r]}("");
            require(success, "Call failed");
            balances[r] = 0; // side-effect after external call
        }
    }

    function deposit() nonReentrant public payable {
        balances[msg.sender] += msg.value;       
    }

}