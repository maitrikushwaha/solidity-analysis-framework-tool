pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    bool flag = false;
    mapping (address => uint256) public balances;

    function toggle() internal {
        flag = !flag;
    }

    function withdraw(uint256 amt) public {
        //require(!flag, "Locked");
        toggle();

        require(balances[msg.sender] >= amt, "Insufficient funds");
        (bool success, ) = msg.sender.call{value:amt}("");
        require(success, "Call failed");
        balances[msg.sender] -= amt; // automatic revert in Solidity 0.8+ if underflows happens

        toggle();
    }

    function deposit() public payable {
        require(!flag, "Locked");
        balances[msg.sender] += msg.value;       
    }

}