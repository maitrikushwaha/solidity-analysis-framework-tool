pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;
    event Withdrawn(uint amt);

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        payable(msg.sender).transfer(balances[msg.sender]);
        balances[msg.sender] = 0;

        (bool success, ) = msg.sender.call{value:0}("");
        require(success, "Call failed");

        emit Withdrawn(balances[msg.sender]);
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}