pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;

    event Sent(uint256 amt);
    event Paid(uint256 amt);

    function pay(uint256 amt) internal {
        (bool success2, ) = msg.sender.call{value:amt}("");
        require(success2, "Call failed");
        emit Paid(amt);
    }

    function withdraw() public {
        require(balances[msg.sender] > 0, "Insufficient funds");
        bool success1 = payable(msg.sender).send(balances[msg.sender]);
        require(success1, "Send failed");
        emit Sent(balances[msg.sender]);
        balances[msg.sender] = 0;
        pay(0);
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}