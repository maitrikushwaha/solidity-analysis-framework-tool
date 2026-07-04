pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    function pay(uint256 amt) internal {
        (bool success, ) = msg.sender.call{value:amt}("");
        require(success, "Call failed");
    }

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        pay(balances[msg.sender]);
        update();
    }

    function update() internal {
        balances[msg.sender] = 0; // side-effect after external call
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}