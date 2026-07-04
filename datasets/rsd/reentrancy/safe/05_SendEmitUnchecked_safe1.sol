pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    event Sent(uint256 amt);

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        bool success1 = payable(msg.sender).send(balances[msg.sender]);
        require(success1, "Send failed");
        unchecked {
            balances[msg.sender] = 0;
        }
        emit Sent(balances[msg.sender]);
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}