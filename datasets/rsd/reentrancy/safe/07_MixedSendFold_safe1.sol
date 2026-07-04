pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    function pay(uint256 amt) internal {
        (bool success2, ) = msg.sender.call{value:amt}("");
        require(success2, "Call failed");
    }

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        bool success1 = payable(msg.sender).send(balances[msg.sender]);
        require(success1, "Send failed");
        balances[msg.sender] = 0;
        pay(0);
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}