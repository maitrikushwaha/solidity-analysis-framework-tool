pragma solidity ^0.4.25;


contract SimpleEthBank {

    mapping (address => uint) accountBalances;

    function withdraw(uint amount) public {
        accountBalances[msg.sender] -= amount;
        msg.sender.call.value(amount);
    }
}
