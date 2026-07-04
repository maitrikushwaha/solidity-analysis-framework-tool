pragma solidity ^0.8.20;

// SPDX-License-Identifier: GPL-3.0
contract C {
    mapping (address => uint256) public balances;
    mapping (address => bool) private done;

    function withdrawOnlyOnce() public {
        require(!done[msg.sender], "Not allowed!");
        require(balances[msg.sender] > 0, "Insufficient funds");
        done[msg.sender] = true;
        (bool success, ) = msg.sender.call{value:balances[msg.sender]}("");
        require(success, "Call failed");
        balances[msg.sender] = 0;    // this does NOT lead to a reentrancy even though the side-effect is after the call()
        done[msg.sender] = success;
    }

    function deposit() public payable {
        balances[msg.sender] += msg.value;       
    }

}