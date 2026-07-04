pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    bool flag = false;
    mapping (address => uint256) public balances;

    function toggle() internal {
        flag = !flag;
    }

    function withdraw() public {
        require(!flag, "Locked");
        flag = true; // broken
        toggle();

        require(balances[msg.sender] > 0, "Insufficient funds");
        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        balances[msg.sender] = 0; // side-effect after external call

        toggle();
    }

    function deposit() public payable {
        require(!flag, "Locked");
        balances[msg.sender] += msg.value;       
    }

}